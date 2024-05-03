from typing import List


class TimeData:
    def __init__(self, m5, h1, h24):
        self.m5 = m5
        self.h1 = h1
        self.h24 = h24


class Pool:
    def __init__(self, network, address):
        self.network = network
        self.address = address
        self.name = None
        self.dex = None
        self.relative_price = None
        self.fdv = None
        self.volume = None
        self.reserve = None
        self.price_change: TimeData or None = None
        self.buy_sell: TimeData or None = None

    def set(self,
            name = None,
            dex = None,
            relative_price = None,
            fdv = None,
            volume = None,
            reserve = None,
            price_change = None,
            buy_sell = None
            ):
        self.name = name
        self.dex = dex
        self.relative_price = relative_price
        self.fdv = fdv
        self.volume = volume
        self.reserve = reserve
        self.price_change = price_change
        self.buy_sell = buy_sell
        return self

    def get_pretty_name(self) -> str:
        return self.name.upper()

    def get_pretty_dex(self) -> str:
        return 'DeDust' if self.dex == 'dedust' else ('STON fi' if self.dex == 'stonfi' else self.dex)

    def __repr__(self):
        return f'{self.name} {self.dex}'


class Pools:
    def __init__(self):
        self.pools: List[Pool] = []

    def update(self, network, address, **params):
        pool = None
        pool_exists = False

        for p in self.pools:
            if p.network == network and p.address == address:
                pool = p
                pool_exists = True
                break

        if pool_exists: pool.set(**params)
        else: self.pools.append(Pool(network, address).set(**params))

    def find_growing_pools(self) -> List[Pool]:
        return [p for p in self.pools if
                p.price_change.m5 >= 0.01 or p.price_change.h1 >= 0.05
                ]

    def __len__(self):
        return len(self.pools)

    def __repr__(self):
        return '\n'.join([p.__repr__() for p in self.pools])
