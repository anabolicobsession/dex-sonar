import geckoterminal_api

from constants import DEFAULT_NETWORK
from pools import Pools


class GeckoTerminalAPIWrapper(geckoterminal_api.GeckoTerminalAPI):
    def __init__(self, network=DEFAULT_NETWORK, **params):
        super().__init__(**params)
        self.network = network
        self.MAX_PAGES = geckoterminal_api.limits.MAX_PAGE

    def update_pools(self, pools: Pools):
        data = []

        for i in range(1, self.MAX_PAGES + 1):
            new_data = self.network_trending_pools(network=self.network, page=i, include=['quote_token'])['data']
            if new_data: data = [*data, *new_data]
            else: break

        for d in data:
            a = d['attributes']
            pools.update(
                d['id'],
                name = a['name'].lower(),
                dex = d['relationships']['dex']['data']['id'],
                m5 = float(a['price_change_percentage']['m5']) / 100,
                h1 = float(a['price_change_percentage']['h1']) / 100,
            )
