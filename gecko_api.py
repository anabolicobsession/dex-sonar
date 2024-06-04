import asyncio
import logging

from aiohttp import ClientResponseError
from geckoterminal_api import AsyncGeckoTerminalAPI, limits

import settings
from utils import DateTime
from network import Pools, TimeData, Address, Token, DEXId, DEX, Pool

logger = logging.getLogger(__name__)

COOLDOWN_INITIAL_TIME = 10
COOLDOWN_INCREASING_FACTOR = 1.2


class UnexpectedValueError(Exception): pass


class GeckoTerminalAPIWrapper(AsyncGeckoTerminalAPI):
    def __init__(self, max_requests=30, **params):
        super().__init__(**params)
        self.max_requests = max_requests
        self.requests = None

    async def update_pools(self, pools: Pools):
        self._clear_requests()

        top_pools_data, top_pools_meta = await self._request_pools_data(self.network_pools)
        trending_pools_data, trending_pools_meta = await self._request_pools_data(self.network_trending_pools)

        data = {**top_pools_data, **trending_pools_data}
        meta = {**top_pools_meta, **trending_pools_meta}

        logger.info(f'Tokens: Total:{len(meta)} = Top:{len(top_pools_meta)} & Trending:{len(trending_pools_meta)}')

        tokens: dict[Address, Token] = {}
        dexes: dict[DEXId, DEX] = {}

        # prepare information about every token or dex without taking into account pools themselves
        for x in meta.values():
            x = x | x['attributes']

            match x['type']:

                case 'token':
                    address = x['address']
                    if address not in tokens: tokens[address] = Token(address, ticker=x['symbol'])

                case 'dex':
                    id = x['id']
                    if id not in dexes: dexes[id] = DEX(id, name=x['name'])

                case _:
                    raise UnexpectedValueError(x['type'])

        for x in data.values():
            x = x | x['attributes'] | x['relationships']

            base_token = tokens[x['base_token']['data']['id'].split('_', 1)[1]]
            quote_token = tokens[x['quote_token']['data']['id'].split('_', 1)[1]]

            transactions = x['transactions']
            price_change = {k: float(v) / 100 for k, v in x['price_change_percentage'].items()}

            buys_m5,  sells_m5 =  int(transactions['m5'] ['buys']),  int(transactions['m5'] ['sells'])
            buys_m15, sells_m15 = int(transactions['m15']['buys']), int(transactions ['m15']['sells'])
            buys_h1,  sells_h1 =  int(transactions['h1'] ['buys']),  int(transactions['h1'] ['sells'])
            buys_h24, sells_h24 = int(transactions['h24']['buys']), int(transactions ['h24']['sells'])

            buyers_m5,  sellers_m5 =  int(transactions['m5'] ['buyers']),  int(transactions['m5'] ['sellers'])
            buyers_m15, sellers_m15 = int(transactions['m15']['buyers']), int(transactions ['m15']['sellers'])
            buyers_h1,  sellers_h1 =  int(transactions['h1'] ['buyers']),  int(transactions['h1'] ['sellers'])
            buyers_h24, sellers_h24 = int(transactions['h24']['buyers']), int(transactions ['h24']['sellers'])

            volume = {k: float(v) for k, v in x['volume_usd'].items()}

            flippers = int(min(buyers_h24, sellers_h24) * settings.FLIPPER_PERCENT)
            makers = buyers_h24 + sellers_h24 - flippers

            # some values may be missing
            if not x['base_token_price_native_currency']:
                logger.info(f'Base token price in native currency is not set - {base_token}')
                continue

            pools.update(Pool(
                x['address'],
                base_token=base_token,
                quote_token=quote_token,
                dex=dexes[x['dex']['data']['id']],
                creation_date=DateTime.fromisoformat(x['pool_created_at']),

                price=float(x['base_token_price_usd']),
                price_in_native_token=float(x['base_token_price_native_currency']),
                fdv=float(x['fdv_usd']),
                market_cap=float(x['market_cap_usd']) if x['market_cap_usd'] else None,
                volume=volume['h24'],
                liquidity=float(x['reserve_in_usd']),
                transactions=buys_h24 + sells_h24,
                makers=makers,

                price_change=TimeData(
                    m5= price_change['m5'],
                    h1= price_change['h1'],
                    h6= price_change['h6'],
                    h24=price_change['h24'],
                ),
                buys_sells_ratio=TimeData(
                    m5= max(buys_m5, 1)  / max(sells_m5, 1),
                    m15=max(buys_m15, 1) / max(sells_m15, 1),
                    h1= max(buys_h1, 1)  / max(sells_h1, 1),
                    h24=max(buys_h24, 1) / max(sells_h24, 1),
                ),
                buyers_sellers_ratio=TimeData(
                    m5= max(buyers_m5, 1)  / max(sellers_m5, 1),
                    m15=max(buyers_m15, 1) / max(sellers_m15, 1),
                    h1= max(buyers_h1, 1)  / max(sellers_h1, 1),
                    h24=max(buyers_h24, 1) / max(sellers_h24, 1),
                ),
                volume_ratio=TimeData(
                    m5=volume['m5'] / (volume['h24'] / (24 * 12)) if volume['h24'] else 1,
                    h1=volume['h1'] / (volume['h24'] / 24)        if volume['h24'] else 1,
                    h6=volume['h6'] / (volume['h24'] / 4)         if volume['h24'] else 1,
                    h24=1,
                )
            ))

    def _clear_requests(self):
        self.requests = 0

    def _has_requests(self):
        return self.requests < self.max_requests

    def _increase_requests(self):
        self.requests += 1

    async def _request_pools_data(self, request_fun) -> tuple[dict, dict]:
        data = {}
        meta = {}
        cooldown = COOLDOWN_INITIAL_TIME

        for i in range(1, limits.MAX_PAGE + 1):
            if not self._has_requests():
                break

            response = None
            while not response:
                try:
                    response = await request_fun(network=settings.NETWORK, page=i)

                #  API wrapper has a bug where it throws "KeyError" instead of the correct request limit exception
                except (ClientResponseError, KeyError) as e:
                    postfix = f'{e.status}: {e.message}' if isinstance(e, ClientResponseError) else str(e)
                    logger.warning(f'Request limit exceeded: {postfix}')

                except Exception as e:
                    logger.warning(f'Unknown exception: {e}')

                if not response:
                    logger.warning(f'Waiting for {cooldown:.0f}s')
                    await asyncio.sleep(cooldown)
                    cooldown *= COOLDOWN_INCREASING_FACTOR
            self._increase_requests()

            if response['data']:
                data = data | {x['id']: x for x in response['data']}
                meta = meta | {x['id']: x for x in response['included']}
            # there are no more data at page i
            else:
                break

        return data, meta
