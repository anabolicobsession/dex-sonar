import os
import logging
from datetime import timedelta

def _get_time(**kwargs):
    return timedelta(**kwargs).total_seconds()


_DEVELOPMENT_MODE = False
_PRODUCTION_MODE = not _DEVELOPMENT_MODE

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TON_API_KEY = os.environ.get('TON_API_KEY')
WHITELIST_ID = {int(os.environ.get('DEVELOPER_TELEGRAM_ID'))}

NETWORK = 'ton'
NETWORK_NATIVE_CURRENCY_ADDRESS = 'EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c'

UPDATES_COOLDOWN = _get_time(minutes=2) if _PRODUCTION_MODE else _get_time(seconds=10)
GECKO_TERMINAL_MAX_REQUESTS_PER_CYCLE = 25 if _PRODUCTION_MODE else 3

NOTIFICATION_PUMP_COOLDOWN = _get_time(hours=2) if _PRODUCTION_MODE else _get_time(minutes=1)

NOTIFICATION_USER_WALLET_CHANGE_BOUND = 0.05
NOTIFICATION_COOLDOWN_WALLET = _get_time(minutes=10)

POOL_DEFAULT_FILTER = (
    lambda p:
    p.quote_token.is_native_currency() and
    p.liquidity > 10_000
)

PUMPED_POOL_MIN_SCORE_HIGH_LIQUIDITY = 5
PUMPED_POOL_MIN_SCORE_LOW_LIQUIDITY = 12 if _PRODUCTION_MODE else PUMPED_POOL_MIN_SCORE_HIGH_LIQUIDITY
LIQUIDITY_BOUND = 50_000


def calculate_pool_growth_score(p):
    return (2 * p.price_change.m5 + p.price_change.h1) * 100


def is_pumped_pool(p):
    score = calculate_pool_growth_score(p)
    return score > PUMPED_POOL_MIN_SCORE_HIGH_LIQUIDITY if p.liquidity > LIQUIDITY_BOUND else score > PUMPED_POOL_MIN_SCORE_LOW_LIQUIDITY


TELEGRAM_MESSAGE_MAX_LEN = 3700
TELEGRAM_MESSAGE_MAX_WIDTH = 36

COMMAND_START = 'start'
COMMAND_START_MESSAGE = 'You\'ve subscribed to growing pool updates'

DATABASES_DIR_PATH = 'data'
os.makedirs(DATABASES_DIR_PATH, exist_ok=True)
DATABASES_PATH_USERS = os.path.join(DATABASES_DIR_PATH, 'users.csv' if _PRODUCTION_MODE else 'development.csv')
DATABASES_PATH_MUTELISTS = os.path.join(DATABASES_DIR_PATH, 'mutelists.csv')

LOGGING_LEVEL = logging.INFO
LOGGING_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOGGING_DIR_PATH = 'logs'
os.makedirs(LOGGING_DIR_PATH, exist_ok=True)
LOGGING_PATH_WARNINGS = os.path.join(LOGGING_DIR_PATH, 'warnings.log')
LOGGING_PATH_DEBUG = os.path.join(LOGGING_DIR_PATH, 'debug.log')

TELEGRAM_FORBIDDEN_BLOCK = 'Forbidden: bot was blocked by the user'
TELEGRAM_BAD_REQUEST_MESSAGE_IS_TOO_LONG = 'Message is too long'
TELEGRAM_BAD_REQUEST_MESSAGE_IS_NOT_MODIFIED = 'Message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message'
TELEGRAM_MESSAGE_TO_EDIT_NOT_FOUND = 'Message to edit not found'
TELEGRAM_CHAT_NOT_FOUND = 'Chat not found'
