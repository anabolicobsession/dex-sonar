from datetime import timedelta
from typing import Callable, Iterable, Iterator, TypeVar

from dex_sonar.network_and_pools.network import DEX, Token
from dex_sonar.network_and_pools.pool_with_chart import IncompleteTick, Pool
from dex_sonar.utils.time import Timestamp


def floor_timestamp_to_minutes(timestamp: Timestamp) -> Timestamp:
    return timestamp - timedelta(
        seconds=timestamp.second,
        microseconds=timestamp.microsecond,
    )


T = TypeVar('T')

class SetWithGet(set):
    def get(self, item: T, default=None) -> T | None:
        for x in self:
            if x == item: return x
        return default


Filter = Callable[[Pool], bool]
FilterKey = Callable[[Pool], float]

PoolsType = SetWithGet[Pool]
Tokens = SetWithGet[Token]
DEXes = SetWithGet[DEX]


class Pools:
    def __init__(
            self,
            pool_filter: Filter | None = None,
            repeated_pool_filter_key: FilterKey | None = None,
    ):
        self.pools: SetWithGet = SetWithGet()
        self.tokens: SetWithGet = SetWithGet()
        self.dexes: SetWithGet = SetWithGet()

        self.pool_filter = pool_filter
        self.repeated_pool_filter_key = repeated_pool_filter_key

    def __len__(self):
        return len(self.pools)

    def __iter__(self) -> Iterator[Pool]:
        return iter(self.pools)

    def get_tokens(self) -> list[Token]:
        return [x for x in self.tokens]

    def get_dexes(self) -> list[DEX]:
        return [x for x in self.dexes]

    def _ensure_consistent_token_and_dex_references(self, pool: Pool):
        if x := self.tokens.get(pool.base_token):
            x.update(pool.base_token)
            pool.base_token = x
        else:
            self.tokens.add(pool.base_token)

        if x := self.tokens.get(pool.quote_token):
            x.update(pool.quote_token)
            pool.quote_token = x
        else:
            self.tokens.add(pool.quote_token)

        if x := self.dexes.get(pool.dex):
            x.update(pool.dex)
            pool.dex = x
        else:
            self.dexes.add(pool.dex)

    def _update(self, pool: Pool):
        if existing_pool := self.pools.get(pool):
            existing_pool.update(pool)
        else:
            self.pools.add(pool)

    def update(
            self,
            pools: Pool | Iterable[Pool],
            timestamp_of_update: Timestamp = None,
    ):
        if not timestamp_of_update:
            timestamp_of_update = Timestamp.now()

        for pool in pools if isinstance(pools, Iterable) else [pools]:

            previous_price_native = self.pools.get(pool).price_native if pool in self.pools else None

            if self.pool_filter and not self.pool_filter(pool):
                continue

            if self.repeated_pool_filter_key:
                existing_pool = None

                for p in self.pools:
                    # if it's not literally the same pool, but a pool with same tokens, but different DEX
                    if p != pool and p.base_token == pool.base_token and p.quote_token == pool.quote_token:
                        existing_pool = p
                        break

                if existing_pool:
                    if self.repeated_pool_filter_key(pool) > self.repeated_pool_filter_key(existing_pool):
                        self.pools.remove(existing_pool)
                        self.dexes = DEXes([p.dex for p in self.pools])
                    else:
                        continue

            self._ensure_consistent_token_and_dex_references(pool)
            self._update(pool)

            if pool.price_native != previous_price_native or pool.chart.is_empty():
                pool.chart.update(
                    IncompleteTick(
                        timestamp=floor_timestamp_to_minutes(timestamp_of_update),
                        price=pool.price_native,
                    )
                )

    def apply_filter(self):
        if self.pools and self.pool_filter:
            self.pools = SetWithGet(filter(self.pool_filter, self.pools))
            self.tokens = Tokens(Tokens(map(lambda p: p.base_token, self.pools)) | Tokens(map(lambda p: p.quote_token, self.pools)))
            self.dexes = SetWithGet(map(lambda p: p.dex, self.pools))

    def match_pool(self, token: Token, pool_filter_key: FilterKey) -> Pool | None:
        matches = [p for p in self.pools if p.base_token == token and p.quote_token.is_native_currency()]

        if matches:
            if not self.repeated_pool_filter_key:
                matches.sort(key=pool_filter_key, reverse=True)
            return matches[0]

        return None
