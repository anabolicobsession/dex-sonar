import geckoterminal_api

import settings
from pools import Pools, TimeData


class GeckoTerminalAPIWrapper(geckoterminal_api.GeckoTerminalAPI):
    def __init__(self, max_requests_per_minute=30, **params):
        super().__init__(**params)
        self.MAX_PAGES = geckoterminal_api.limits.MAX_PAGE
        self.MAX_REQUESTS_PER_MINUTE = max_requests_per_minute
        self.DEFAULT_POOL_NAME_SEPARATOR = '/'

    def update_pools(self, pools: Pools, network, max_requests=None) -> Pools:
        data = []
        requests = 0
        max_requests = self.MAX_REQUESTS_PER_MINUTE if max_requests is None else max_requests

        for i in range(1, self.MAX_PAGES + 1):
            if requests == max_requests: break
            new_data = self.network_trending_pools(network=network, page=i, include=['quote_token'])['data']
            requests += 1
            if new_data: data = [*data, *new_data];
            else: break

        for i in range(1, self.MAX_PAGES + 1):
            if requests == max_requests: break
            new_data = self.network_pools(network=network, page=i, include=['quote_token'])['data']
            requests += 1
            if new_data: data = [*data, *new_data];
            else: break

        for d in data:
            a = d['attributes']
            name = a['name'].lower(); name = name.split(self.DEFAULT_POOL_NAME_SEPARATOR, 1)[0].strip() if settings.DEFAULT_NETWORK in name else name
            price_change = a['price_change_percentage']
            transactions = a['transactions']

            if network not in a['name'].lower().split(self.DEFAULT_POOL_NAME_SEPARATOR, 1)[1].strip():
                continue

            pools.update(
                network,
                a['address'],
                name = name,
                dex = d['relationships']['dex']['data']['id'],
                relative_price = float(a['base_token_price_native_currency']),
                fdv = float(a['fdv_usd']),
                volume = float(a['volume_usd']['h24']),
                reserve = float(a['reserve_in_usd']),
                price_change = TimeData(float(price_change['m5']) / 100, float(price_change['h1']) / 100, float(price_change['h24']) / 100),
                buy_sell = TimeData(
                    int(transactions['m5']['buys']) / int(transactions['m5']['sells']) - 1 if int(transactions['m5']['sells']) > 0 else 0,
                    int(transactions['h1']['buys']) / int(transactions['h1']['sells']) - 1 if int(transactions['h1']['sells']) > 0 else 0,
                    int(transactions['h24']['buys']) / int(transactions['h24']['sells']) - 1 if int(transactions['h24']['sells']) > 0 else 0,
                )
            )

        return pools
