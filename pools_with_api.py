import logging
from datetime import timedelta

import api.geckoterminal_api as gapi
import api.dex_screener_api as dapi
import settings
from network import Pools

logger = logging.getLogger(__name__)


NETWORK = settings.NETWORK


class PoolsWithAPI(Pools):
    REQUESTS_TIMEOUT_RESET = timedelta(seconds=60)
    CHECK_FOR_NEW_TOKENS_EVERY_UPDATE = 30

    def __init__(self, **params):
        super().__init__(**params)
        self.geckoterminal_api = gapi.GeckoTerminalAPI()
        self.dex_screener_api = dapi.DEXScreenerAPI()
        self.update_counter = 0
        
    async def close_api_sessions(self):
        await self.geckoterminal_api.close()
        await self.dex_screener_api.close()

    async def update(self):
        geckoterminal_api_requests = 0
        dex_screener_api_requests = 0
        
        if self.update_counter % PoolsWithAPI.CHECK_FOR_NEW_TOKENS_EVERY_UPDATE == 0:
            self.geckoterminal_api.get_top_pools(NETWORK)
            pass

