from datetime import timedelta
from logging import INFO, DEBUG

from .configparser import Config
from ..network.network import Network, Pool


config = Config()
config.read('config.ini')
config.read('dev_config.ini')


TESTING_MODE = config.getboolean('Bot', 'testing_mode')
NOT_TESTING_MODE = not TESTING_MODE

NETWORK = Network.TON
TIMESTAMP_UNIT = timedelta(minutes=1)

MUTELISTS_DATABASE_NAME = 'mutelists' if NOT_TESTING_MODE else '_mutelists'
USERS_DATABASE_NAME = 'users' if NOT_TESTING_MODE else '_users'

LOGGING_LEVEL = INFO if not config.getboolean('Logs', 'debug_mode') else DEBUG
LOGGING_FORMAT = '%(name)s - %(levelname)s - %(message)s' if NOT_TESTING_MODE else '%(asctime)s - %(name)s - %(levelname)s - %(message)s'


def pool_filter(p: Pool):
    return (
        p.liquidity > config.getint('Pools', 'min_liquidity') and
        p.volume > config.getint('Pools', 'min_volume')
    )
