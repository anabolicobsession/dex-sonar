import asyncio
import logging
from statistics import mean
from typing import Callable

import geckoterminal_api
import requests.exceptions
from geckoterminal_api import GeckoTerminalAPIError

import settings
from utils import Datetime
from network import Pools, TimeData, Address, Token, DEXId, DEX

logger = logging.getLogger(__name__)


class UnexpectedValueError(Exception): pass


class GeckoTerminalAPIWrapper(geckoterminal_api.GeckoTerminalAPI):
    def __init__(self, max_requests=30, **params):
        super().__init__(**params)
        self.MAX_PAGES = geckoterminal_api.limits.MAX_PAGE
        self.MAX_REQUESTS = max_requests
        self.requests = None

    def _has_requests(self):
        return self.requests < self.MAX_REQUESTS

    def _increase_requests(self):
        self.requests += 1

    def _clear_requests(self):
        self.requests = 0

    async def _request_data(self, request: Callable) -> tuple[dict, dict]:
        data = {}
        included = {}

        for i in range(1, self.MAX_PAGES + 1):
            if not self._has_requests():
                break

            response = None
            sleep = 10
            while not response:
                try:
                    response = request(network=settings.NETWORK, page=i)

                except KeyError as e:
                    logger.info(f'Request limit exceeded')

                except requests.ReadTimeout as e:
                    logger.warning(f'{e}')

                except GeckoTerminalAPIError as e:
                    logger.warning(e)

                if not response:
                    logger.info(f'Sleeping for {sleep}s')
                    await asyncio.sleep(sleep)
                    sleep *= 1.5
            self._increase_requests()

            if response['data']:
                data = data | {x['id']: x for x in response['data']}
                included = included | {x['id']: x for x in response['included']}
            else:
                break

        return data, included

    async def update_pools(self, pools: Pools):
        self._clear_requests()

        data, included = await self._request_data(self.network_pools)
        new_data, new_included = await self._request_data(self.network_new_pools)

        old_data_len = len(data)
        data, included = {**data, **new_data}, {**included, **new_included}
        logger.info(f'Total pools: {len(data)}, Top pools: {old_data_len}, New pools: {len(new_data)}')

        tokens: dict[Address, Token] = {}
        dexes: dict[DEXId, DEX] = {}

        for x in included.values():
            x = x | x['attributes']

            match x['type']:
                case 'token':
                    address = x['address']

                    if address not in tokens:
                        tokens[address] = Token(address, ticker=x['symbol'])
                case 'dex':
                    id = x['id']

                    if id not in dexes:
                        dexes[id] = DEX(id, name=x['name'])
                case _:
                    raise UnexpectedValueError(x['type'])

        for x in data.values():
            x = x | x['attributes'] | x['relationships']

            transactions = x['transactions']
            price_change = x['price_change_percentage']

            buys_m5, sells_m5 = int(transactions['m5']['buys']), int(transactions['m5']['sells'])
            buys_h1, sells_h1 = int(transactions['h1']['buys']), int(transactions['h1']['sells'])
            buys_h24, sells_h24 = int(transactions['h24']['buys']), int(transactions['h24']['sells'])

            buyers_m5, sellers_m5 = int(transactions['m5']['buyers']), int(transactions['m5']['sellers'])
            buyers_h1, sellers_h1 = int(transactions['h1']['buyers']), int(transactions['h1']['sellers'])
            buyers_h24, sellers_h24 = int(transactions['h24']['buyers']), int(transactions['h24']['sellers'])

            pools.update_pool(
                x['address'],
                base_token=tokens[x['base_token']['data']['id'].split('_', 1)[1]],
                quote_token=tokens[x['quote_token']['data']['id'].split('_', 1)[1]],
                dex=dexes[x['dex']['data']['id']],
                creation_date=Datetime.fromisoformat(x['pool_created_at']),
                price=float(x['base_token_price_usd']),
                price_in_native_currency=float(x['base_token_price_native_currency']),
                fdv=float(x['fdv_usd']),
                volume=float(x['volume_usd']['h24']),
                liquidity=float(x['reserve_in_usd']),
                transactions=buys_h24 + sells_h24,
                makers=round(mean([buyers_h24, sellers_h24])),
                transactions_per_wallet=(buyers_h24 * (buys_h24 / buyers_h24 if buyers_h24 else 0) + sellers_h24 * (sells_h24 / sellers_h24 if sellers_h24 else 0)) / (buyers_h24 + sellers_h24 if buyers_h24 or sellers_h24 else 0),
                price_change=TimeData(float(price_change['m5']) / 100, float(price_change['h1']) / 100, float(price_change['h24']) / 100),
                buys_sells_ratio=TimeData(
                    buys_m5 / sells_m5 if buys_m5 and sells_m5 else 1,
                    buys_h1 / sells_h1 if buys_h1 and sells_h1 else 1,
                    buys_h24 / sells_h24 if buys_h24 and sells_h24 else 1,
                ),
                buyers_sellers_ratio=TimeData(
                    buyers_m5 / sellers_m5 if buyers_m5 and sellers_m5 else 1,
                    buyers_h1 / sellers_h1 if buyers_h1 and sellers_h1 else 1,
                    buyers_h24 / sellers_h24 if buyers_h24 and sellers_h24 else 1,
                )
            )
