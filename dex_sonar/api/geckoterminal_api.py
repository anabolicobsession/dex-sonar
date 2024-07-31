from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable

from pydantic import AwareDatetime, BaseModel, Field

from dex_sonar.api.api import API, EmptyData, JSON
from dex_sonar.api.request_limits import RequestLimits, StrictRateLimiter
from dex_sonar.utils.time import Timedelta


NetworkId = str
Address = str


class ValueOutOfDomain(Exception):
    ...


class PoolSource(Enum):
    TOP = ''
    TRENDING = 'trending_'


class Page:

    Type = int
    MIN = 1
    MAX = 10

    def __init__(self, page: Type):
        if not self.MIN <= page <= self.MAX:
            raise ValueOutOfDomain(
                f'Page number {page} is out of range [{self.MIN}, {self.MAX}]'
            )
        self.page = page


class PageInterval:
    def __init__(self, start: Page.Type, end: Page.Type):
        self.start = Page(start)
        self.end = Page(end)
        if not self.start.page <= self.end.page:
            raise ValueError(
                f'Start page {self.start.page} can\'t come after end page {self.end.page}'
            )

    def __iter__(self):
        return iter(range(self.start.page, self.end.page + 1))


AllPages = PageInterval(Page.MIN, Page.MAX)


class SortBy(Enum):
    TRANSACTIONS = 'h24_tx_count_desc'
    VOLUME = 'h24_volume_usd_desc'


@dataclass(frozen=True)
class Timeframe:
    class Day(Enum):
        ONE = 1

    class Hour(Enum):
        ONE = 1
        FOUR = 4
        TWELVE = 12

    class Minute(Enum):
        ONE = 1
        FIVE = 5
        FIFTEEN = 15


class Currency(Enum):
    USD = 'usd'
    TOKEN = 'token'


class Pool(BaseModel):
    network_id: NetworkId
    address: Address


class Candlestick(BaseModel):
    timestamp: AwareDatetime = Field(...)
    open: float = Field(...)
    high: float = Field(...)
    low: float = Field(...)
    close: float = Field(...)
    volume: float = Field(...)


class GeckoTerminalAPI(API):

    NAME = 'GeckoTerminal API'
    REQUEST_LIMITS = RequestLimits(
        max=30,
        time_period=Timedelta(minutes=1),
    )
    RATE_LIMITER_TYPE = StrictRateLimiter

    def __init__(self, **kwargs):
        super().__init__(
            base_url='https://api.geckoterminal.com/api/v2',
            **kwargs,
        )

    async def _get_json(self, *url_path_segments, **params) -> JSON:
        return await super()._get_json(*url_path_segments, **params)

    async def get_pools(
            self,
            network: NetworkId,
            pool_sources: PoolSource | Iterable[PoolSource] = PoolSource.TOP,
            pages: Page | PageInterval = Page.MIN,
            sort_by: SortBy = SortBy.TRANSACTIONS
    ) -> list[Pool]:

        pools = []

        for pool_source in pool_sources if isinstance(pool_sources, Iterable) else [pool_sources]:

            for page in pages if isinstance(pages, PageInterval) else PageInterval(Page, Page):

                json = await self._get_json(
                    'networks', network, pool_source.value + 'pools',
                    params={
                        'page': page,
                        'sort': sort_by.value,
                    }
                )

                if pools_json := json['data']:
                    pools.extend(
                        [
                            Pool(
                                **{
                                    'network_id': network,
                                    **pool_json['attributes']
                                }
                            )
                            for pool_json in pools_json
                        ]
                    )
                else:
                    break

        return pools

    async def get_ohlcv(
            self,
            network: NetworkId,
            pool_address: Address,
            timeframe: Timeframe.Day | Timeframe.Hour | Timeframe.Minute = Timeframe.Day.ONE,
            currency: Currency = Currency.USD,
            before_timestamp: datetime | None = None,
    ) -> list[Candlestick]:

        json = await self._get_json(
            'networks', network, 'pools', pool_address, 'ohlcv', timeframe.__class__.__name__.lower(),
            params={
                'aggregate': timeframe.value,
                'currency': currency.value,
                'before_timestamp':
                    int(
                        before_timestamp.astimezone(timezone.utc).timestamp()
                        if before_timestamp
                        else datetime.now(timezone.utc).timestamp()
                    ),
                'limit': 1000,
            }
        )

        ohclv = json['data']['attributes']['ohlcv_list'][::-1]

        if not ohclv:
            raise EmptyData('OHCLV list is empty')

        return [Candlestick(
            timestamp=x[0],
            open=     x[1],
            high=     x[2],
            low=      x[3],
            close=    x[4],
            volume=   x[5],
        ) for x in ohclv]
