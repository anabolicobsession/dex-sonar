import csv
from typing import Callable

import settings
from utils import DateTime

Address = str
DEXId = str


class TimeData:
    def __init__(
            self,
            m5=None,
            m15=None,
            h1=None,
            h6=None,
            h24=None,
    ):
        self.m5 = m5
        self.m15 = m15
        self.h1 = h1
        self.h6 = h6
        self.h24 = h24


class Token:
    def __init__(self, address, ticker=None, decimals=None):
        self.address: str = address
        self.ticker = ticker
        self.decimals = decimals

    def __eq__(self, other):
        if isinstance(other, Token):
            return self.address == other.address
        return False

    def __hash__(self):
        return self.address.__hash__()

    def __repr__(self):
        return self.ticker

    def update(self, force=False, ticker=None, decimals=None):
        if (force or not self.ticker) and ticker: self.ticker = ticker
        if (force or not self.decimals) and decimals: self.decimals = decimals

    def is_native_currency(self):
        return self.address == settings.NETWORK_NATIVE_CURRENCY_ADDRESS


class DEX:
    def __init__(self, id, name=None):
        self.id = id
        self.name = name

    def update(self, name=None):
        if not self.name and name: self.name = name


class Pool:
    def __init__(
            self,
            address,
            base_token,
            quote_token,
            dex,
            creation_date: DateTime,

            price,
            price_in_native_token,
            fdv,
            market_cap,
            volume,
            liquidity,
            transactions,
            makers,

            price_change: TimeData,
            buys_sells_ratio: TimeData,
            buyers_sellers_ratio: TimeData,
            volume_ratio: TimeData
    ):
        self.address: Address = address
        self.base_token: Token = base_token
        self.quote_token: Token = quote_token
        self.dex: DEX = dex
        self.creation_date: DateTime = creation_date

        self.price = price
        self.price_in_native_token = price_in_native_token
        self.fdv = fdv
        self.market_cap = market_cap
        self.volume = volume
        self.liquidity = liquidity
        self.transactions = transactions
        self.makers = makers

        self.price_change: TimeData = price_change
        self.buys_sells_ratio: TimeData = buys_sells_ratio
        self.buyers_sellers_ratio: TimeData = buyers_sellers_ratio
        self.volume_ratio: TimeData = volume_ratio

    def __eq__(self, other):
        if isinstance(other, Pool):
            return self.address == other.address
        return False

    def __hash__(self):
        return self.address.__hash__()

    def __repr__(self):
        return self.base_token.ticker + '/' + self.quote_token.ticker


class Pools:
    def __init__(
            self,
            pool_filter: Callable[[Pool], bool] | None = None,
            repeated_pool_filter_key: Callable[[Pool], float] | None = None,
    ):
        self.pools: list[Pool] = []
        self.tokens: dict[Address, Token] = {}
        self.dexes: dict[DEXId, DEX] = {}
        self.blacklist = dict[Address, str]
        self.pool_filter = pool_filter
        self.repeated_pool_filter_key = repeated_pool_filter_key

        with open(settings.BLACKLIST_FILENAME, 'r') as file:
            self.blacklist = dict(csv.reader(file))

    def __len__(self):
        return len(self.pools)

    def __getitem__(self, index) -> Pool:
        return self.pools[index]

    def clear(self):
        self.pools = []
        self.tokens = {}
        self.dexes = {}

    def has_token(self, token: Token) -> bool:
        return token.address in self.tokens

    def get_token(self, address: Address) -> Token | None:
        return self.tokens.get(address, None)

    def get_tokens(self) -> list[Token]:
        return list(self.tokens.values())

    def add(self, pool):
        if pool.base_token.address in self.blacklist.keys():
            return

        if self.pool_filter and not self.pool_filter(pool):
            return

        if self.repeated_pool_filter_key:
            pool_with_same_token = None

            for p in self.pools:
                if p.base_token == pool.base_token:
                    pool_with_same_token = p
                    break

            if pool_with_same_token:
                if self.repeated_pool_filter_key(pool) > self.repeated_pool_filter_key(pool_with_same_token):
                    self.pools.remove(pool_with_same_token)
                else:
                    return

        self.pools.append(pool)
        self.tokens[pool.base_token.address] = pool.base_token
        self.tokens[pool.quote_token.address] = pool.quote_token
        self.dexes[pool.dex.id] = pool.dex

    def find_best_token_pool(self, token: Token, key: Callable) -> Pool | None:
        pools = [p for p in self.pools if p.base_token == token]
        if pools:
            pools.sort(key=key, reverse=True)
            return pools[0]
        return None
