from dataclasses import dataclass
from typing import Callable

import settings

Address = Id = str


class Token:
    def __init__(self, address, symbol=None, decimals=None):
        self.address: str = address
        self.symbol = symbol
        self.decimals = decimals

    def __eq__(self, other):
        if isinstance(other, Token):
            return self.address == other.address
        return False

    def __hash__(self):
        return self.address.__hash__()

    def update(self, force=False, symbol=None, decimals=None):
        if (force or not self.symbol) and symbol: self.symbol = symbol
        if (force or not self.decimals) and decimals: self.decimals = decimals

    def is_native_currency(self):
        return self.address == settings.NETWORK_NATIVE_CURRENCY_ADDRESS


class DEX:
    def __init__(self, id, name=None):
        self.id = id
        self.name = name

    def update(self, name=None):
        if not self.name and name: self.name = name


@dataclass
class TimeData:
    m5: float
    h1: float
    h24: float


class Pool:
    def __init__(self,
                 address,
                 base_token,
                 quote_token,
                 dex,
                 price,
                 price_in_native_currency,
                 fdv,
                 volume,
                 liquidity,
                 transactions,
                 makers,
                 transactions_per_wallet,
                 price_change,
                 buy_sell_change,
                 buyers_sellers_change,
                 ):
        self.address: Address = address
        self.base_token: Token = base_token
        self.quote_token: Token = quote_token
        self.dex: DEX = dex
        self.price = price
        self.price_in_native_currency = price_in_native_currency
        self.fdv = fdv
        self.volume = volume
        self.liquidity = liquidity
        self.transactions = transactions
        self.makers = makers
        self.transactions_per_wallet = transactions_per_wallet
        self.price_change: TimeData = price_change
        self.buy_sell_change: TimeData = buy_sell_change
        self.buyers_sellers_change: TimeData = buyers_sellers_change

    def __eq__(self, other):
        if isinstance(other, Pool):
            return self.address == other.address
        return False

    def __hash__(self):
        return self.address.__hash__()


class Pools:
    def __init__(self):
        self.pools: list[Pool] = []
        self.tokens: dict[Address, Token] = {}
        self.dexes: dict[Id, DEX] = {}
        self.blacklist: set[Token] = {Token(a, symbol=s) for s, a in settings.TOKEN_BLACKLIST.items()}

    def __len__(self):
        return len(self.pools)

    def update_token(self, address, **data):
        if address not in self.tokens:
            self.tokens[address] = Token(address, **data)
        else:
            self.tokens[address].update(**data)

    def get_token(self, address) -> Token | None:
        if address in self.tokens:
            return self.tokens[address]
        return None

    def get_tokens(self) -> list[Token]:
        return list(self.tokens.values())

    def update_dex(self, id, **data):
        if id not in self.dexes:
            self.dexes[id] = DEX(id, **data)
        else:
            self.dexes[id].update(**data)

    def get_dex(self, id) -> DEX:
        return self.dexes[id]

    def get_dexes(self) -> list[DEX]:
        return list(self.dexes.values())

    def update_pool(self, address, **data):
        pool = Pool(address, **data)

        if pool.quote_token.is_native_currency():
            if pool.base_token not in self.blacklist and pool.quote_token not in self.blacklist:
                self.pools.append(pool)

    def get_pools(self):
        return self.pools

    def filter_repeated_pools(self, key_fun: Callable, reverse=False):
        new_pools = {}

        def condition(p1, p2):
            return key_fun(p1) < key_fun(p2)

        for pool in self.pools:
            key = frozenset([pool.base_token, pool.quote_token])

            if key not in new_pools or (condition(pool, new_pools[key]) ^ reverse):
                new_pools[key] = pool

        self.pools = list(new_pools.values())

    def select_pools(self, filter_fun: Callable) -> list[Pool]:
        return [p for p in self.pools if filter_fun(p)]

    def find_best_token_pool(self, token: Token) -> Pool | None:
        pools = [p for p in self.pools if p.base_token == token]
        if pools:
            pools.sort(key=lambda p: p.volume, reverse=True)
            return pools[0]
        return None
