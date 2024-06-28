from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, AwareDatetime

from api.base_api import BaseAPI, JSON, EmptyData


NetworkId = str
Address = str
Page = int
PageInterval = tuple[Page, Page]


class PoolSource(Enum):
    TOP = ''
    TRENDING = 'trending_'


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
    address: Address = Field(...)


class Candlestick(BaseModel):
    timestamp: AwareDatetime = Field(...)
    open: float = Field(...)
    high: float = Field(...)
    low: float = Field(...)
    close: float = Field(...)
    volume: float = Field(...)


class GeckoTerminalAPI(BaseAPI):

    BASE_URL = 'https://api.geckoterminal.com/api/v2'

    MIN_PAGE = 1
    MAX_PAGE = 10
    ALL_PAGES = (MIN_PAGE, MAX_PAGE)

    def __init__(self, **params):
        super().__init__(GeckoTerminalAPI.BASE_URL, request_limit=30, **params)

    async def _get_json(self, *url_path_segments, **params) -> JSON:
        return (await self._get(*url_path_segments, **params))[0]

    async def get_pools(
            self,
            network: NetworkId,
            pool_source: PoolSource = PoolSource.TOP,
            pages: Page or PageInterval = MIN_PAGE,
            sort_by: SortBy = SortBy.TRANSACTIONS
    ) -> list[Pool]:

        pages = (pages,) if isinstance(pages, int) else range(pages[0], pages[1] + 1)
        pools = []

        for page in pages:
            response_json = await self._get_json(
                'networks', network, pool_source.value + 'pools',
                params={
                    'page': page,
                    'sort': sort_by.value,
                }
            )
            pools.extend([Pool(**{**pool_json, **pool_json['attributes']}) for pool_json in response_json['data']])

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
                'before_timestamp': int(before_timestamp.timestamp()) if before_timestamp else int(datetime.now(timezone.utc).timestamp()),
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
