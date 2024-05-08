import logging
from statistics import mean

import geckoterminal_api
import requests.exceptions

import settings
from pools import Pools, TimeData

logger = logging.getLogger(__name__)


class UnexpectedValueError(Exception):
    pass


class GeckoTerminalAPIWrapper(geckoterminal_api.GeckoTerminalAPI):
    def __init__(self, max_requests=30, **params):
        super().__init__(**params)
        self.MAX_PAGES = geckoterminal_api.limits.MAX_PAGE
        self.MAX_REQUESTS = max_requests

    def update_pools(self, pools: Pools):
        data = {}
        included = {}

        for i in range(1, min(self.MAX_PAGES, self.MAX_REQUESTS) + 1):
            response = None

            while not response:
                try:
                    response = self.network_pools(network=settings.NETWORK, page=i)
                except requests.ReadTimeout as e:
                    logger.info(str(e))

            if response['data']:
                data = data | {x['id']: x for x in response['data']}
                included = included | {x['id']: x for x in response['included']}
            else:
                break

        for x in included.values():
            x = x | x['attributes']

            match x['type']:
                case 'token':
                    pools.update_token(x['address'], symbol=x['symbol'])
                case 'dex':
                    pools.update_dex(x['id'], name=x['name'])
                case _:
                    raise UnexpectedValueError(x['type'])

        for x in data.values():
            x = x | x['attributes'] | x['relationships']
            transactions = x['transactions']
            buys = int(transactions['h24']['buys'])
            sells = int(transactions['h24']['sells'])
            buyers = int(transactions['h24']['buyers'])
            sellers = int(transactions['h24']['sellers'])
            price_change = x['price_change_percentage']

            pools.update_pool(
                x['address'],
                base_token=pools.get_token(x['base_token']['data']['id'].split('_', 1)[1]),
                quote_token=pools.get_token(x['quote_token']['data']['id'].split('_', 1)[1]),
                dex=pools.get_dex(x['dex']['data']['id']),
                price=float(x['base_token_price_usd']),
                price_in_native_currency=float(x['base_token_price_native_currency']),
                fdv=float(x['fdv_usd']),
                volume=float(x['volume_usd']['h24']),
                liquidity=float(x['reserve_in_usd']),
                transactions=buys + sells,
                makers=round(mean([buyers, sellers])),
                transactions_per_wallet=(buyers * (buys / buyers) + sellers * (sells / sellers)) / (buyers + sellers),
                price_change=TimeData(float(price_change['m5']) / 100, float(price_change['h1']) / 100, float(price_change['h24']) / 100),
                buy_sell_change=TimeData(
                    int(transactions['m5']['buys']) / int(transactions['m5']['sells']) - 1 if int(transactions['m5']['sells']) > 0 else 0,
                    int(transactions['h1']['buys']) / int(transactions['h1']['sells']) - 1 if int(transactions['h1']['sells']) > 0 else 0,
                    buys / sells - 1 if sells > 0 else 0,
                ),
                buyers_sellers_change=TimeData(
                    int(transactions['m5']['buyers']) / int(transactions['m5']['sellers']) - 1 if int(transactions['m5']['sellers']) > 0 else 0,
                    int(transactions['h1']['buyers']) / int(transactions['h1']['sellers']) - 1 if int(transactions['h1']['sellers']) > 0 else 0,
                    buyers / sellers - 1 if sellers > 0 else 0,
                )
            )
