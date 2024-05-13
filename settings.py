import logging
import os

NETWORK = 'ton'
NETWORK_NATIVE_CURRENCY_ADDRESS = 'EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c'

UPDATES_COOLDOWN = 90
GECKO_TERMINAL_MAX_REQUESTS_PER_CYCLE = 20  # can use up to 20 requests

MINUTE = 60
HOUR = MINUTE * 60
NOTIFICATIONS_USER_WALLET_CHANGE_BOUND = 0.05
NOTIFICATIONS_PUMP_COOLDOWN = HOUR * 2

TELEGRAM_MESSAGE_MAX_LEN = 3700  # the actual limit is lower than 4096

COMMAND_HELP_DESCRIPTION = 'How to use bot'
COMMAND_HELP_MESSAGE = '''
Bot has 3 types of messages:

1. Pinned message - edited on every update cycle. It shows growing pools.

2. Alert - sends a message after every pump.

3. Alert for user wallet - sends a message after evey dump or pump with user tokens.
'''
COMMAND_RESEND_DESCRIPTION = 'Send the pinned message again'

DATA_DIR_PATH = 'data'
os.makedirs(DATA_DIR_PATH, exist_ok=True)
PINNED_MESSAGES_IDS_PATH = os.path.join(DATA_DIR_PATH, 'pinned_messages_ids.csv')
FOLLOWLISTS_PATH = os.path.join(DATA_DIR_PATH, 'followlists.csv')

LOGGING_LEVEL = logging.INFO
LOGGING_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOGGING_DIR_PATH = 'logs'
os.makedirs(LOGGING_DIR_PATH, exist_ok=True)
LOGGING_WARNINGS_PATH = os.path.join(LOGGING_DIR_PATH, 'warnings.log')

BAD_REQUEST_MESSAGE_IS_TOO_LONG = 'Message is too long'
BAD_REQUEST_MESSAGE_IS_NOT_MODIFIED = 'Message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message'
