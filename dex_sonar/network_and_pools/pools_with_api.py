import logging
from asyncio import sleep
from copy import deepcopy
from logging import getLogger
from typing import Awaitable, Callable, Iterable, Sequence

from dex_sonar.api.dex_screener_api import DEXScreenerAPI, Pool as DEXScreenerPool
from dex_sonar.api.geckoterminal_api import AllPages, Candlestick as GeckoTerminalCandlestick, Currency, GeckoTerminalAPI, Pool as GeckoTerminalPool, PoolSource, SortBy, Timeframe
from dex_sonar.config.config import NETWORK_ID
from dex_sonar.network_and_pools.network import Address, DEX, Network, TimePeriodsData, Token
from dex_sonar.network_and_pools.pool_with_chart import CompleteTick, Pool, TIMESTAMP_UNIT
from dex_sonar.network_and_pools.pools import Pools
from dex_sonar.utils.time import Cooldown, Timedelta, Timestamp


logger = getLogger(__name__)


_THERE_WAS_NO_UPDATE = -1


def exponential_average(current_average, new_value, alpha=0.05):
    return current_average * (1 - alpha) + new_value * alpha


def dex_screener_pool_to_pool(p: DEXScreenerPool) -> Pool | None:
    if not all([
        p.price_usd,
        p.fdv,
        p.liquidity,
        p.creation_date,
    ]):
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
        dex=DEX(id=p.dex_id),

        price_native=p.price_native,
        price_usd=p.price_usd,
        fdv=p.fdv,
        volume=p.volume.h24,
        liquidity=p.liquidity.total,

        price_change=TimePeriodsData(
            m5=p.price_change.m5,
            h1=p.price_change.h1,
            h6=p.price_change.h6,
            h24=p.price_change.h24,
        ),
        creation_date=Timestamp.from_other(p.creation_date),
    )


def dex_screener_pools_to_pools(pools: Sequence[DEXScreenerPool]) -> list[Pool]:
    converted_pools = [dex_screener_pool_to_pool(p) for p in pools]
    null_pools = [pools[i] for i, p in enumerate(converted_pools) if p is None]

    if null_pools:
        logger.debug(
            f'Excluded pools because missing some mandatory properties:\n' +
            '\n'.join(

                [f'{p.base_token.ticker} ({Network.from_id(p.network_id).get_name()}/{p.address})' for p in null_pools]
            )
        )

    return list(filter(None, converted_pools))


def geckoterminal_candlesticks_to_ticks(candlesticks: Iterable[GeckoTerminalCandlestick]) -> list[CompleteTick]:
    ticks = []

    for c in candlesticks:
        if not ticks or c.timestamp > ticks[-1].timestamp + TIMESTAMP_UNIT:
            ticks.append(
                CompleteTick(
                    timestamp=Timestamp.from_other(c.timestamp - TIMESTAMP_UNIT),
                    price=c.open,
                    volume=0,
                )
            )

        ticks.append(
            CompleteTick(
                timestamp=Timestamp.from_other(c.timestamp),
                price=c.close,
                volume=c.volume,
            )
        )

    return ticks


class PoolsWithAPI(Pools):
    def __init__(
            self,
            additional_cooldown: Timedelta = Timedelta(),
            callback_coroutine: Callable[[], Awaitable] = lambda: None,

            do_intermediate_updates: bool = False,
            intermediate_update_duration: Timedelta | None = None,
            starting_intermediate_update_duration_estimate: Timedelta = Timedelta(),

            fetch_new_pools_every_update: int = 60,
            dex_screener_delay: Timedelta = Timedelta(),

            request_error_cooldown: Cooldown = None,

            **kwargs,
    ):
        super().__init__(**kwargs)

        self.geckoterminal_api = GeckoTerminalAPI(request_error_cooldown=deepcopy(request_error_cooldown))
        self.dex_screener_api = DEXScreenerAPI(request_error_cooldown=deepcopy(request_error_cooldown))

        self.first_update_start: Timestamp = None
        self.update_start: Timestamp = None
        self.update_end: Timestamp = None
        self.update_counter = 0
        self.last_chart_update: dict[Pool, int] = {}

        self.additional_cooldown = additional_cooldown
        self.coroutine_callback = callback_coroutine

        self.do_intermediate_updates = do_intermediate_updates
        self.intermediate_update_duration = intermediate_update_duration
        self.average_intermediate_update_duration_without_cooldown = starting_intermediate_update_duration_estimate

        self.fetch_new_pools_every_update = fetch_new_pools_every_update
        self.dex_screener_delay = dex_screener_delay

    async def update_via_api(self):
        if not self.first_update_start: self.first_update_start = Timestamp.now()
        self.update_start = Timestamp.now()
        self.update_end = None

        self._log_general_info()

        addresses_for_update = set(x.address for x in self)

        if self._does_update_satisfy(self.fetch_new_pools_every_update):
            addresses_for_update |= set(x.address for x in await self._get_new_pools_via_geckoterminal())

        await self._update_pools_via_dex_screener(list(addresses_for_update))
        self.apply_filter()

        await self._update_charts_with_historical_data_via_geckoterminal()
        if self.additional_cooldown: self.update_end = Timestamp.now() + self._time_left() + self.additional_cooldown

        await self.coroutine_callback()

        self._log_pools()

        if self.do_intermediate_updates:
            await self._run_intermediate_updates()

        if cooldown := self._time_left():
            if cooldown >= Timedelta(seconds=1): logger.info(f'Waiting until update ends {cooldown.total_seconds():.0f}s')
            await sleep(cooldown.total_seconds())

        logger.info(f'Total time: {self.update_start.time_elapsed_in_seconds():.0f}s')
        logger.info('')

        self._increment_update_counter()

    async def close_api_sessions(self):
        await self.geckoterminal_api.close()
        await self.dex_screener_api.close()

    @staticmethod
    def get_update_duration_estimate() -> Timedelta:
        return max(
            GeckoTerminalAPI.REQUEST_LIMITS.time_period,
            DEXScreenerAPI.REQUEST_LIMITS.time_period
        )

    def _log_general_info(self):
        logger.info(
            f'Starting update #{self.update_counter + 1} '
            '(' +
            ', '.join([
                f'pools: {len(self)}',
                f'uptime: {self.first_update_start.time_elapsed_in_seconds() / 60:.0f} min',
                f'average update duration: {round(self.first_update_start.time_elapsed_in_seconds() / self.update_counter) if self.update_counter else 0:.0f}s',
                f'average intermediate pure update duration: {round(self.average_intermediate_update_duration_without_cooldown.total_seconds()):.0f}s',
            ])
            + ')'
        )

    def _log_pools(self):
        if logger.isEnabledFor(logging.DEBUG):
            lines = []

            for p in self:
                lines.append(f'{p.get_shortened_name()}: {p.chart}')

            logger.debug('Pools:\n' + '\n'.join(lines))

    def _increment_update_counter(self):
        self.update_counter += 1

    def _does_update_satisfy(self, every_update):
        return self.update_counter % every_update == 0

    async def _get_new_pools_via_geckoterminal(self) -> list[GeckoTerminalPool]:
        return await self.geckoterminal_api.get_pools(
            network=NETWORK_ID,
            pool_sources=[PoolSource.TRENDING, PoolSource.TOP],
            pages=AllPages,
            sort_by=SortBy.VOLUME,
        )

    async def _update_pools_via_dex_screener(self, addresses: Sequence[Address] = None):
        self.update(
            pools=dex_screener_pools_to_pools(await self.dex_screener_api.get_pools(network=NETWORK_ID, addresses=addresses if addresses else [p.address for p in self])),
            timestamp_of_update=Timestamp.now() - self.dex_screener_delay,
        )

    async def _update_charts_with_historical_data_via_geckoterminal(self):
        # priority of chart update is based on 2 numbers,
        # the recency of the update and the volume multiplied by the magnitude of hourly price change
        priority_list = [
            [
                x,
                self.last_chart_update.get(x, _THERE_WAS_NO_UPDATE),
                x.volume * abs(x.price_change.h1),
            ] for x in self
        ]

        priority_list.sort(key=lambda t: (t[1], -t[2]))
        priority_pools = [t[0] for t in priority_list[:self.geckoterminal_api.get_available_requests()]]

        for pool in priority_pools:
            pool.chart.update(
                geckoterminal_candlesticks_to_ticks(
                    await self.geckoterminal_api.get_ohlcv(
                        network=NETWORK_ID,
                        address=pool.address,
                        timeframe=Timeframe.Minute.ONE,
                        currency=Currency.TOKEN,
                    )
                )
            )
            self.last_chart_update[pool] = self.update_counter

    async def _run_intermediate_updates(self):
        call_start_timestamp = Timestamp.now()
        updates = 0
        first = True

        async def run_intermediate_updates_without_cooldown():
            start = Timestamp.now()

            nonlocal first
            if first:
                logger.info('Running intermediate updates')
                first = False

            await self._update_pools_via_dex_screener()
            await self.coroutine_callback()

            self.average_intermediate_update_duration_without_cooldown = exponential_average(
                current_average=self.average_intermediate_update_duration_without_cooldown,
                new_value=start.time_elapsed(),
            )

            nonlocal updates
            updates += 1
            return start

        if self.intermediate_update_duration:
            def check_if_duration_condition_is_met():
                if self.intermediate_update_duration < self.average_intermediate_update_duration_without_cooldown:
                    self.intermediate_update_duration = self.average_intermediate_update_duration_without_cooldown
                    logger.warning(
                        f'Parameter \'intermediate_update_duration\' ({self.intermediate_update_duration.total_seconds():.1f}s) '
                        f'is less than the intermediate update duration without cooldown itself ({self.average_intermediate_update_duration_without_cooldown.total_seconds():.1f}s). '
                        f'So the value of parameter can\'t be fulfilled and is set to the latter value. '
                        f'Either increase the parameter value or set it to be null to turn off intermediate update cooldowns at all'
                    )

            check_if_duration_condition_is_met()

            while self._time_left() >= self.intermediate_update_duration:
                start_timestamp = await run_intermediate_updates_without_cooldown()
                check_if_duration_condition_is_met()
                await sleep(self.intermediate_update_duration.positive_difference(start_timestamp.time_elapsed()).total_seconds())
        else:
            while self._time_left() >= self.average_intermediate_update_duration_without_cooldown:
                await run_intermediate_updates_without_cooldown()

        if updates:
            logger.info(f'Ran intermediate updates: {updates} in {call_start_timestamp.time_elapsed_in_seconds():.0f}s')

    def _time_left(self) -> Timedelta:
        if not self.update_end:
            return max(
                self.geckoterminal_api.get_time_until_new_requests_can_be_made(
                    number_of_requests=min(
                        len(self),
                        GeckoTerminalAPI.REQUEST_LIMITS.max,
                    )
                ),
                self.dex_screener_api.get_time_until_new_requests_can_be_made(
                    number_of_requests=self.dex_screener_api.estimate_requests_per_get_pools_call(
                        number_of_pools=len(self)
                    )
                ),
            )
        else:
            return self.update_end.time_left()
