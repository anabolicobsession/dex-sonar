from datetime import datetime

from pydantic import BaseModel, Field

from api.base_api import BaseAPI, JSON, UnsupportedSchema


class Token(BaseModel):
    address: str = Field(...)
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
    network: str = Field(..., alias='chainId')
    address: str = Field(..., alias='pairAddress')
    base_token: Token = Field(..., alias='baseToken')
    quote_token: Token = Field(..., alias='quoteToken')

    price_usd: float = Field(..., alias='priceUsd')
    price_native: float = Field(..., alias='priceNative')
    liquidity: Liquidity = Field(...)
    fdv: float = Field(...)

    price_change: TimePeriodsData = Field(..., alias="priceChange")
    volume: TimePeriodsData = Field(..., alias="volume")
    transactions: TimePeriodsTransactionCounts = Field(..., alias="txns")

    dex_id: str = Field(..., alias='dexId')
    creation_date: datetime = Field(..., alias='pairCreatedAt')
    url: str = Field(...)


class DEXScreenerAPI(BaseAPI):

    BASE_URL = 'https://api.dexscreener.io/latest/dex'
    SCHEMA_VERSION = '1.0.0'
    REQUESTS_LIMIT_PER_MINUTE = 300

    NetworkId = str
    Address = str

    def __init__(self, **params):
        super().__init__(DEXScreenerAPI.BASE_URL, **params)

    async def _get_json(self, *url_path_segments) -> JSON:
        json = (await self._get(*url_path_segments))[0]

        if json['schemaVersion'] != DEXScreenerAPI.SCHEMA_VERSION:
            raise UnsupportedSchema(DEXScreenerAPI.SCHEMA_VERSION, json['schemaVersion'])

        return json

    async def get_pools(self, network: NetworkId, pools: Address | list[Address]) -> list[Pool]:
        pools_segment = pools if isinstance(pools, DEXScreenerAPI.Address) else ','.join(pools)
        json = await self._get_json('pairs', network, pools_segment)
        return [Pool(**pool_json) for pool_json in json['pairs']]
