import logging
from datetime import timedelta, timezone, datetime
from itertools import chain
from typing import Collection

from api.base_api import Cooldown
from network import Network, Token, DEX
from extended_pool import Pool, CompleteTick, TimePeriodsData, IncompleteTick
from pools import Pools
from api.geckoterminal_api import GeckoTerminalAPI, PoolSource, SortBy, Timeframe, Currency, \
    Candlestick as GeckoTerminalCandlestick
from api.dex_screener_api import DEXScreenerAPI, Pool as DEXScreenerPool
import settings


_TIMEFRAME = timedelta(seconds=60)
_NO_UPDATE = -1
COOLDOWN = 10


logger = logging.getLogger(__name__)


def make_batches(sequence: list, n: int) -> list[list]:
    return [sequence[i:n + i] for i in range(0, len(sequence), n)]


class PoolsWithAPI(Pools):

    REQUESTS_RESET_TIMEOUT = timedelta(seconds=60)
    CHECK_FOR_NEW_TOKENS_EVERY_UPDATE = 20
    APPLY_FILTER_EVERY_UPDATE = 20

    def __init__(self, **params):
        super().__init__(**params)
        self.geckoterminal_api = GeckoTerminalAPI(cooldown=Cooldown(timedelta(seconds=COOLDOWN), 1.5))
        self.dex_screener_api = DEXScreenerAPI(cooldown=Cooldown(timedelta(seconds=COOLDOWN), 1.5))
        self.update_counter = 0
        self.last_chart_update: dict[Pool, int] = {}
        
    async def close_api_sessions(self):
        await self.geckoterminal_api.close()
        await self.dex_screener_api.close()

    def _increment_update_counter(self):
        self.update_counter += 1

    def _satisfy(self, every_update):
        return self.update_counter % every_update == 0

    @staticmethod
    def _dex_screener_pool_to_pool(p: DEXScreenerPool) -> Pool:
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

            price_usd=p.price_usd,
            price_native=p.price_native,
            liquidity=p.liquidity.total,
            volume=p.volume.h24,
            fdv=p.fdv,

            price_change=TimePeriodsData(
                m5=p.price_change.m5,
                h1=p.price_change.h1,
                h6=p.price_change.h6,
                h24=p.price_change.h24,
            ),
            dex=DEX(p.dex_id),
            creation_date=p.creation_date,
        )

    @staticmethod
    def _geckoterminal_candlesticks_to_ticks(candlesticks: Collection[GeckoTerminalCandlestick]) -> list[CompleteTick]:
        ticks = []

        for c in candlesticks:
            if not ticks or c.timestamp > ticks[-1].timestamp + _TIMEFRAME:
                ticks.append(
                    CompleteTick(
                        timestamp=c.timestamp - _TIMEFRAME,
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

    async def update_using_api(self):
        if self._satisfy(PoolsWithAPI.APPLY_FILTER_EVERY_UPDATE):
            self.apply_filter()

        new_pools = []
        if self._satisfy(PoolsWithAPI.CHECK_FOR_NEW_TOKENS_EVERY_UPDATE):
            for source in (PoolSource.TOP, PoolSource.TRENDING):
                new_pools.extend(await self.geckoterminal_api.get_pools(
                    settings.NETWORK.get_id(),
                    pool_source=source,
                    pages=GeckoTerminalAPI.ALL_PAGES,
                    sort_by=SortBy.VOLUME,
                ))

        timestamp = datetime.now(timezone.utc)
        rounded_timestamp = timestamp - timedelta(
            seconds=timestamp.second,
            microseconds=timestamp.microsecond,
        )

        new_addresses = [x.address for x in new_pools]
        all_addresses = list(set([p.address for p in self]) | set(new_addresses))

        self.update(
            list(chain(*[
                map(
                    self._dex_screener_pool_to_pool,
                    await self.dex_screener_api.get_pools(settings.NETWORK.get_id(), batch)
                )
                for batch in make_batches(all_addresses, DEXScreenerAPI.MAX_ADDRESSES)
            ]))
        )

        for p in self:
            p.chart.update(IncompleteTick(rounded_timestamp, p.price_native))

        priority_list = [
            [
                p,
                self.last_chart_update.get(p, _NO_UPDATE),
                p.volume * abs(p.price_change.h1),
            ] for p in self
        ]
        priority_list.sort(key=lambda t: (t[1], -t[2]))
        pools_for_chart_update = [t[0] for t in priority_list[:self.geckoterminal_api.get_requests_left()]]

        for pool in pools_for_chart_update:
            pool.chart.update(
                self._geckoterminal_candlesticks_to_ticks(
                    await self.geckoterminal_api.get_ohlcv(
                        settings.NETWORK.get_id(),
                        pool_address=pool.address,
                        timeframe=Timeframe.Minute.ONE,
                        currency=Currency.TOKEN,
                    )
                )
            )
            self.last_chart_update[pool] = self.update_counter

        self._increment_update_counter()
        self.geckoterminal_api.reset_request_counter()
        self.dex_screener_api.reset_request_counter()
