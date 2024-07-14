from datetime import timedelta

from .configparser import config
from ..network.network import Network, Pool


NETWORK = Network.TON
TIMESTAMP_UNIT = timedelta(minutes=1)


def pool_filter(p: Pool):
    return (
        p.liquidity > config.getint('Pools', 'min_liquidity') and
        p.volume > config.getint('Pools', 'min_volume')
    )
