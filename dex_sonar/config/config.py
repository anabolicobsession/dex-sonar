import logging
from datetime import timezone

from dex_sonar.config.configparser import Config


config = Config()
config.read('config.ini')
config.read('dev.ini')


TESTING_MODE = config.getboolean('Bot', 'testing_mode')
NOT_TESTING_MODE = not TESTING_MODE


if TESTING_MODE:
    config.read('testing.ini')


NETWORK_ID = 'ton'
TIMEZONE = timezone.utc

LOGGING_LEVEL = logging.INFO if not config.getboolean('Logs', 'debug_mode') else logging.DEBUG
LOGGING_FORMAT = (
    '%(name)s :: %(levelname)s :: %(message)s'
    if NOT_TESTING_MODE else
    '%(asctime)s :: %(name)s :: %(message)s'
)
LOGGING_TIMESTAMP_FORMAT = '%m-%d %H:%M:%S'
