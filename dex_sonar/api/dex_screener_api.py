import logging

from pydantic import BaseModel, Field, AwareDatetime

from .base_api import BaseAPI, JSON, UnsupportedSchema


NetworkId = str
Address = str


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
    liquidity: Liquidity = None
    volume: TimePeriodsData = Field(..., alias='volume')
    fdv: float = None

    price_change: TimePeriodsData = Field(..., alias='priceChange')
    transactions: TimePeriodsTransactionCounts = Field(..., alias='txns')
    creation_date: AwareDatetime = Field(default=None, alias='pairCreatedAt')
    url: str


class DEXScreenerAPI(BaseAPI):
    BASE_URL = 'https://api.dexscreener.io/latest/dex'
    SCHEMA_VERSION = '1.0.0'
    MAX_ADDRESSES = 30

    def __init__(self, **params):
        super().__init__(DEXScreenerAPI.BASE_URL, request_limit=300, **params)

    async def _get_json(self, *url_path_segments) -> JSON:
        json = (await self._get(*url_path_segments))[0]

        if json['schemaVersion'] != DEXScreenerAPI.SCHEMA_VERSION:
            raise UnsupportedSchema(DEXScreenerAPI.SCHEMA_VERSION, json['schemaVersion'])

        return json

    async def get_pools(
            self,
            network: NetworkId,
            address_or_addresses: Address | list[Address]
    ) -> list[Pool]:

        pools_segment = address_or_addresses if isinstance(address_or_addresses, Address) else ','.join(address_or_addresses)
        json = await self._get_json('pairs', network, pools_segment)

        if not json['pairs']:
            logging.warning(f"Empty 'pairs' attribute for pool addresses:\n{','.join(address_or_addresses)}")
            raise Exception()

        return [Pool(**pool_json) for pool_json in json['pairs']]
