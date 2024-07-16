from datetime import timedelta, timezone, datetime
from itertools import chain
from typing import Iterable

from ..config.config import config, TIMESTAMP_UNIT, NETWORK
from .pools import Pools
from .network import Network, Token, DEX, TimePeriodsData
from .pool_with_chart import Pool, CompleteTick, IncompleteTick
from ..api.base_api import Cooldown
from ..api.geckoterminal_api import GeckoTerminalAPI, PoolSource, SortBy, Timeframe, Currency, Candlestick as GeckoTerminalCandlestick
from ..api.dex_screener_api import DEXScreenerAPI, Pool as DEXScreenerPool


_NO_UPDATE = -1


def make_batches(sequence: list, n: int) -> list[list]:
    return [sequence[i:n + i] for i in range(0, len(sequence), n)]


class PoolsWithAPI(Pools):
    def __init__(self, **params):
        super().__init__(**params)
        self.geckoterminal_api = GeckoTerminalAPI(cooldown=Cooldown(timedelta(seconds=10), 1.5))
        self.dex_screener_api = DEXScreenerAPI(cooldown=Cooldown(timedelta(seconds=10), 1.5))
        self.update_counter = 0
        self.chart_last_update: dict[Pool, int] = {}
        
    async def close_api_sessions(self):
        await self.geckoterminal_api.close()
        await self.dex_screener_api.close()

    def _increment_update_counter(self):
        self.update_counter += 1

    def _satisfy_update(self, every_update):
        return self.update_counter % every_update == 0

    async def update_using_api(self):
        if self._satisfy_update(config.getint('Pools', 'apply_filter_every_update')):
            self.apply_filter()

        new_pools = await self._get_top_and_trending_pools()

        # fix timestamp before making requests
        timestamp = datetime.now(timezone.utc)
        rounded_timestamp = timestamp - timedelta(
            minutes=1,
            seconds=timestamp.second,
            microseconds=timestamp.microsecond,
        )

        new_addresses = [x.address for x in new_pools]
        all_addresses = list(set(p.address for p in self) | set(new_addresses))
        await self._update_pools(all_addresses)

        # update charts using previously defined fixed timestamp with latest price
        for p in self:

            # print(f'{p.base_token.ticker}:')
            # print(p.chart)
            # print(f'New tick: {IncompleteTick(rounded_timestamp, p.price_native)}')

            p.chart.update(IncompleteTick(rounded_timestamp, p.price_native))

            # print(p.chart)

        # update only some charts with historical data
        await self._update_charts_by_priority()

        self._increment_update_counter()
        self.geckoterminal_api.reset_request_counter()
        self.dex_screener_api.reset_request_counter()

    @staticmethod
    def _dex_screener_pool_to_pool(p: DEXScreenerPool) -> Pool | None:
        if not p.liquidity:
            return None

        return Pool(
            network=Network.from_id(p.network_id),
            address=p.address,
            base_token=Token(
                network=Network.from_id(p.network_id),
                address=p.base_token.address,
                ticker=p.base_token.ticker,
                name=p.base_token.name,
            ),
            quote_token=Token(
                network=Network.from_id(p.network_id),
                address=p.quote_token.address,
                ticker=p.quote_token.ticker,
                name=p.quote_token.name,
            ),
            dex=DEX(p.dex_id),

            price_native=p.price_native,
            liquidity=p.liquidity.total,
            volume=p.volume.h24,
            price_change=TimePeriodsData(
                m5=p.price_change.m5,
                h1=p.price_change.h1,
                h6=p.price_change.h6,
                h24=p.price_change.h24,
            ),

            price_usd=p.price_usd,
            fdv=p.fdv,
            creation_date=p.creation_date,
        )

    @staticmethod
    def _geckoterminal_candlesticks_to_ticks(candlesticks: Iterable[GeckoTerminalCandlestick]) -> list[CompleteTick]:
        ticks = []

        for c in candlesticks:
            if not ticks or c.timestamp > ticks[-1].timestamp + TIMESTAMP_UNIT:
                ticks.append(
                    CompleteTick(
                        timestamp=c.timestamp - TIMESTAMP_UNIT,
                        price=c.open,
                        volume=0,
                    )
                )

            ticks.append(
                CompleteTick(
                    timestamp=c.timestamp,
                    price=c.close,
                    volume=c.volume,
                )
            )

        return ticks

    async def _get_top_and_trending_pools(self):
        new_pools = []

        if self._satisfy_update(config.getint('Pools', 'fetch_new_every_update')):

            for source in (PoolSource.TOP, PoolSource.TRENDING):

                new_pools.extend(
                    await self.geckoterminal_api.get_pools(
                        NETWORK.get_id(),
                        pool_source=source,
                        pages=GeckoTerminalAPI.ALL_PAGES,
                        sort_by=SortBy.VOLUME,
                    )
                )

        return new_pools

    async def _update_pools(self, addresses):
        self.update(
            filter(
                None,
                (
                    chain(*[
                        map(
                            self._dex_screener_pool_to_pool,
                            await self.dex_screener_api.get_pools(NETWORK.get_id(), batch)
                        )
                        for batch in make_batches(addresses, DEXScreenerAPI.MAX_ADDRESSES)
                    ])
                )
            )
        )

    async def _update_charts_by_priority(self):

        # priority of chart update is based on the 2 numbers,
        # the recency of the update and the volume multiplied by the magnitude of hourly price change
        priority_list = [
            [
                p,
                self.chart_last_update.get(p, _NO_UPDATE),
                p.volume * abs(p.price_change.h1),
            ] for p in self
        ]

        priority_list.sort(key=lambda t: (t[1], -t[2]))
        priority_pools = (t[0] for t in priority_list[:self.geckoterminal_api.get_requests_left()])

        for pool in priority_pools:

            # print(f'{pool.base_token.ticker}: OHLCV')
            # print(pool.chart)

            pool.chart.update(
                self._geckoterminal_candlesticks_to_ticks(
                    await self.geckoterminal_api.get_ohlcv(
                        NETWORK.get_id(),
                        pool_address=pool.address,
                        timeframe=Timeframe.Minute.ONE,
                        currency=Currency.TOKEN,
                    )
                )
            )
            self.chart_last_update[pool] = self.update_counter

            # print(pool.chart)
