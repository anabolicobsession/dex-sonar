from math import ceil
from typing import Sequence

from pydantic import AwareDatetime, BaseModel, Field

from dex_sonar.api.api import API, EmptyData, JSON, UnsupportedSchema
from dex_sonar.api.request_limits import RequestLimits, SmartRateLimiter
from dex_sonar.utils.time import Timedelta


NetworkId = str
Address = str


def make_batches(sequence: Sequence, divider: int) -> list[Sequence]:
    return [
        sequence[i:divider + i]
        for i in range(0, len(sequence), divider)
    ]


class Token(BaseModel):
    address: Address = Field(...)
    ticker: str = Field(..., alias='symbol')
    name: str = Field(...)


class TimePeriodsData(BaseModel):
    m5: float = Field(...)
    h1: float = Field(...)
    h6: float = Field(...)
    h24: float = Field(...)


class TransactionCounts(BaseModel):
    buys: int = Field(...)
    sells: int = Field(...)


class TimePeriodsTransactionCounts(BaseModel):
    m5: TransactionCounts = Field(...)
    h1: TransactionCounts = Field(...)
    h6: TransactionCounts = Field(...)
    h24: TransactionCounts = Field(...)


class Liquidity(BaseModel):
    total: float = Field(..., alias='usd')
    base: float = Field(...)
    quote: float = Field(...)


class Pool(BaseModel):
    network_id: NetworkId = Field(..., alias='chainId')
    address: Address = Field(..., alias='pairAddress')
    base_token: Token = Field(..., alias='baseToken')
    quote_token: Token = Field(..., alias='quoteToken')
    dex_id: str = Field(..., alias='dexId')

    price_native: float = Field(..., alias='priceNative')
    price_usd: float = Field(default=None, alias='priceUsd')
    fdv: float = Field(default=None)
    volume: TimePeriodsData = Field(..., alias='volume')
    liquidity: Liquidity = Field(default=None)

    price_change: TimePeriodsData = Field(..., alias='priceChange')
    transactions: TimePeriodsTransactionCounts = Field(..., alias='txns')
    creation_date: AwareDatetime = Field(default=None, alias='pairCreatedAt')
    url: str = Field(...)


class DEXScreenerAPI(API):

    NAME = 'DEX Screener API'
    REQUEST_LIMITS = RequestLimits(
        max=300,
        time_period=Timedelta(minutes=1),
    )
    RATE_LIMITER_TYPE = SmartRateLimiter

    SCHEMA_VERSION = '1.0.0'
    MAX_ADDRESSES_PER_REQUEST = 30

    def __init__(self, **kwargs):
        super().__init__(
            base_url='https://api.dexscreener.io/latest/dex',
            **kwargs,
        )

    async def _get_json(self, *url_path_segments) -> JSON:
        json = await super()._get_json(*url_path_segments)

        if json['schemaVersion'] != DEXScreenerAPI.SCHEMA_VERSION:
            raise UnsupportedSchema(DEXScreenerAPI.SCHEMA_VERSION, json['schemaVersion'])

        return json

    async def get_pools(self, network: NetworkId, addresses: Address | Sequence[Address]) -> list[Pool]:
        pools = []

        for batch in make_batches(
            sequence=addresses if isinstance(addresses, Sequence) else [addresses],
            divider=self.MAX_ADDRESSES_PER_REQUEST,
        ):
            json = await self._get_json('pairs', network, ','.join(batch))

            if not json['pairs']:
                raise EmptyData(f'Attribute \'pairs\' is empty for addresses:\n{",".join(addresses)}')

            pools.extend([Pool(**pool_json) for pool_json in json['pairs']])

        return pools

    def estimate_requests_per_get_pools_call(self, number_of_pools):
        return ceil(number_of_pools / self.MAX_ADDRESSES_PER_REQUEST)
