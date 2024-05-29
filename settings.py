import os
import logging
from datetime import timedelta


PRODUCTION_MODE = True

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TON_API_KEY = os.environ.get('TON_API_KEY')
DEVELOPER_CHAT_ID = int(os.environ.get('DEVELOPER_TELEGRAM_ID'))
WHITELIST_CHAT_ID = {DEVELOPER_CHAT_ID}

NETWORK = 'ton'
NETWORK_NATIVE_CURRENCY_ADDRESS = 'EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c'


def _get_time(**kwargs):
    return timedelta(**kwargs).total_seconds()


UPDATES_COOLDOWN = _get_time(minutes=2) if PRODUCTION_MODE else _get_time(seconds=10)
GECKO_TERMINAL_MAX_REQUESTS_PER_CYCLE = 30 if PRODUCTION_MODE else 3

NOTIFICATION_PUMP_COOLDOWN = _get_time(hours=2) if PRODUCTION_MODE else 0

NOTIFICATION_USER_WALLET_CHANGE_BOUND = 0.05
NOTIFICATION_COOLDOWN_WALLET = _get_time(minutes=10)

POOL_DEFAULT_FILTER = (
    lambda p:
    p.quote_token.is_native_currency() and
    p.liquidity > 3_000 and
    p.makers > 30
)

if PRODUCTION_MODE:
    PUMPED_POOL_MIN_SCORE_LOW_LIQUIDITY = 15
    PUMPED_POOL_MIN_SCORE_HIGH_LIQUIDITY = 10
else:
    PUMPED_POOL_MIN_SCORE_LOW_LIQUIDITY = 3
    PUMPED_POOL_MIN_SCORE_HIGH_LIQUIDITY = 2
LIQUIDITY_BOUND = 50_000

GROWTH_SCORE_COEFFICIENTS = {
    'm5': 1/6,
    'h1': 1,
    'h6': 1/6,
}

# make up the coefficients to get a total of 1
_GROWTH_SCORE_COEFFICIENTS_SUM = sum(GROWTH_SCORE_COEFFICIENTS.values())
GROWTH_SCORE_COEFFICIENTS = {
    'm5': GROWTH_SCORE_COEFFICIENTS['m5'] / _GROWTH_SCORE_COEFFICIENTS_SUM,
    'h1': GROWTH_SCORE_COEFFICIENTS['h1'] / _GROWTH_SCORE_COEFFICIENTS_SUM,
    'h6': GROWTH_SCORE_COEFFICIENTS['h6'] / _GROWTH_SCORE_COEFFICIENTS_SUM,
}


def calculate_growth_score(p):
    m5 = p.price_change.m5 * GROWTH_SCORE_COEFFICIENTS['m5']
    h1 = p.price_change.h1 * GROWTH_SCORE_COEFFICIENTS['h1']
    h6 = p.price_change.h6 * GROWTH_SCORE_COEFFICIENTS['h6']
    return (m5 + h1 + max(h6, 0)) * 100


def is_growing_pool(p):
    score = calculate_growth_score(p)
    return score > PUMPED_POOL_MIN_SCORE_LOW_LIQUIDITY if p.liquidity < LIQUIDITY_BOUND else score > PUMPED_POOL_MIN_SCORE_HIGH_LIQUIDITY


BLACKLIST_FILENAME = 'blacklist.csv'

TELEGRAM_MESSAGE_MAX_LEN = 3700
TELEGRAM_MESSAGE_MAX_WIDTH = 36

DATABASES_DIR_PATH = 'data'
os.makedirs(DATABASES_DIR_PATH, exist_ok=True)
DATABASES_PATH_USERS = os.path.join(DATABASES_DIR_PATH, 'users.csv' if PRODUCTION_MODE else '_users.csv')
DATABASES_PATH_MUTELISTS = os.path.join(DATABASES_DIR_PATH, 'mutelists.csv' if PRODUCTION_MODE else '_mutelists.csv')

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

FLIPPER_PERCENT = 0.1
