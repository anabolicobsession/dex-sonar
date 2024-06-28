import logging
from datetime import timedelta
import numpy as np

from network import Network


PRODUCTION_MODE = True
PRODUCTION_BOT = True
PRODUCTION_BOT = PRODUCTION_MODE & PRODUCTION_BOT

DATABASE_NAME_MUTELISTS = 'mutelists' if PRODUCTION_MODE else '_mutelists'
DATABASE_NAME_USERS = 'users' if PRODUCTION_MODE else '_users'

UPDATES_COOLDOWN = timedelta(seconds=65).total_seconds()
NOTIFICATION_PUMP_COOLDOWN = timedelta(minutes=30) if PRODUCTION_MODE else timedelta()
GECKO_TERMINAL_MAX_REQUESTS_PER_CYCLE = 30 if PRODUCTION_MODE else 3

POOL_DEFAULT_FILTER = (
    lambda p:
    p.quote_token.is_native_currency() and
    p.liquidity > 10_000 and
    p.volume > 20_000
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


NETWORK = Network.TON

BLACKLIST_FILENAME = 'blacklist.csv'

TELEGRAM_MESSAGE_MAX_LEN = 3700
TELEGRAM_MESSAGE_MAX_WIDTH = 35

LOGGING_LEVEL = logging.DEBUG
LOGGING_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

TELEGRAM_FORBIDDEN_BLOCK = 'Forbidden: bot was blocked by the user'
TELEGRAM_BAD_REQUEST_MESSAGE_IS_TOO_LONG = 'Message is too long'
TELEGRAM_BAD_REQUEST_MESSAGE_IS_NOT_MODIFIED = 'Message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message'
TELEGRAM_MESSAGE_TO_EDIT_NOT_FOUND = 'Message to edit not found'
TELEGRAM_CHAT_NOT_FOUND = 'Chat not found'

FLIPPER_PERCENT = 0.1
