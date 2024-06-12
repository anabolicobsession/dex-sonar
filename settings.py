import os
import logging
from datetime import timedelta

import numpy as np
from dotenv import load_dotenv

load_dotenv('.env')

PRODUCTION_MODE = False
CLOUD = False

DEVELOPERS_CHAt_ID = {int(os.environ.get('DEVELOPER_TELEGRAM_ID'))}
WHITELIST_CHAT_ID = {*DEVELOPERS_CHAt_ID}

NETWORK = 'ton'
NETWORK_NATIVE_CURRENCY_ADDRESS = 'EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c'


def _get_time(**kwargs):
    return timedelta(**kwargs).total_seconds()


UPDATES_COOLDOWN = _get_time(minutes=2) if PRODUCTION_MODE else _get_time(seconds=6)
GECKO_TERMINAL_MAX_REQUESTS_PER_CYCLE = 30 if PRODUCTION_MODE else 3

NOTIFICATION_PUMP_COOLDOWN = _get_time(minutes=30) if PRODUCTION_MODE else 0

CHANGE_BOUND_HIGH = 0.03
CHANGE_BOUND_LOW = 0.01
MIN_BALANCE = 5
NOTIFICATION_COOLDOWN_WALLET = _get_time(minutes=3)

POOL_DEFAULT_FILTER = (
    lambda p:
    p.quote_token.is_native_currency() and
    p.liquidity > 5_000 and
    p.volume > 20_000 and
    p.makers > 60
)

PUMP_MIN_SCORE = 8
DUMP_MIN_SCORE = 5

LIQUIDITY_BOUND = 100_000
CHANGE_SCORE_COEFFICIENTS = {
    'm5': 3,
    'h1': 6,
    'h6': 1,
}


if PRODUCTION_MODE:
    PUMPED_POOL_MIN_SCORE_LOW_LIQUIDITY = PUMP_MIN_SCORE + 5
    PUMPED_POOL_MIN_SCORE_HIGH_LIQUIDITY = PUMP_MIN_SCORE
else:
    PUMPED_POOL_MIN_SCORE_LOW_LIQUIDITY = 5
    PUMPED_POOL_MIN_SCORE_HIGH_LIQUIDITY = 4

CHANGE_SCORE_COEFFICIENTS = {
    'm5': CHANGE_SCORE_COEFFICIENTS['m5'] / sum(CHANGE_SCORE_COEFFICIENTS.values()),
    'h1': CHANGE_SCORE_COEFFICIENTS['h1'] / sum(CHANGE_SCORE_COEFFICIENTS.values()),
    'h6': CHANGE_SCORE_COEFFICIENTS['h6'] / sum(CHANGE_SCORE_COEFFICIENTS.values()),
}


def calculate_change_score(p):
    m5 = p.price_change.m5 * CHANGE_SCORE_COEFFICIENTS['m5']
    h1 = p.price_change.h1 * CHANGE_SCORE_COEFFICIENTS['h1']
    h6 = p.price_change.h6 * CHANGE_SCORE_COEFFICIENTS['h6']
    return (m5 + h1 + np.clip(h6, -1, 1)) * 100


def is_dump(p):
    return calculate_change_score(p) < -DUMP_MIN_SCORE


def is_pump(p):
    score = calculate_change_score(p)

    if p.liquidity < LIQUIDITY_BOUND:
        return score > PUMPED_POOL_MIN_SCORE_LOW_LIQUIDITY
    else:
        return score > PUMPED_POOL_MIN_SCORE_HIGH_LIQUIDITY


def should_be_notified(p):
    return is_pump(p) or is_dump(p)


BLACKLIST_FILENAME = 'blacklist.csv'

TELEGRAM_MESSAGE_MAX_LEN = 3700
TELEGRAM_MESSAGE_MAX_WIDTH = 36

DATABASES_DIR_PATH = 'data' if not CLOUD else os.path.sep + 'tmp'
os.makedirs(DATABASES_DIR_PATH, exist_ok=True)
DATABASES_PATH_USERS = os.path.join(DATABASES_DIR_PATH, 'users.csv' if PRODUCTION_MODE else '_users.csv')
DATABASES_PATH_MUTELISTS = os.path.join(DATABASES_DIR_PATH, 'mutelists.csv' if PRODUCTION_MODE else '_mutelists.csv')

LOGGING_LEVEL = logging.INFO
LOGGING_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

TELEGRAM_FORBIDDEN_BLOCK = 'Forbidden: bot was blocked by the user'
TELEGRAM_BAD_REQUEST_MESSAGE_IS_TOO_LONG = 'Message is too long'
TELEGRAM_BAD_REQUEST_MESSAGE_IS_NOT_MODIFIED = 'Message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message'
TELEGRAM_MESSAGE_TO_EDIT_NOT_FOUND = 'Message to edit not found'
TELEGRAM_CHAT_NOT_FOUND = 'Chat not found'

FLIPPER_PERCENT = 0.1
