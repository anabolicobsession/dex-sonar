from typing import Callable, TypeVar, Iterable, Any

from network import Pool, Token, DEX


T = TypeVar('T')

class SetWithGet(set):
    def my_get(self, element, default = None) -> Any | None:
        for x in self:
            if x == element:
                return x
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

    def __iter__(self):
        return iter(self.pools)

    def get_tokens(self) -> list[DEX]:
        return [x for x in self.tokens]

    def get_dexes(self) -> list[DEX]:
        return [x for x in self.dexes]

    def _ensure_consistent_token_and_dex_references(self, pool: Pool):
        if x := self.tokens.my_get(pool.base_token):
            x.update(pool.base_token)
            pool.base_token = x
        else:
            self.tokens.add(pool.base_token)

        if x := self.tokens.my_get(pool.quote_token):
            x.update(pool.quote_token)
            pool.quote_token = x
        else:
            self.tokens.add(pool.quote_token)

        if x := self.dexes.my_get(pool.dex):
            x.update(pool.dex)
            pool.dex = x
        else:
            self.dexes.add(pool.dex)

    def _update(self, pool: Pool):
        if existing_pool := self.pools.my_get(pool):
            existing_pool.update(pool)
        else:
            self.pools.add(pool)

    def update(self, pools: Pool | Iterable[Pool]):
        for pool in [pools] if isinstance(pools, Pool) else pools:

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

    def apply_filter(self):
        if self.pool_filter:
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
