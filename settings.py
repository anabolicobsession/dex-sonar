import os
import logging

_DEVELOPMENT_MODE = True
_RUNNING_MODE = not _DEVELOPMENT_MODE

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TON_API_KEY = os.environ.get('TON_API_KEY')
DEVELOPER_TELEGRAM_ID = int(os.environ.get('DEVELOPER_TELEGRAM_ID'))

NETWORK = 'ton'
NETWORK_NATIVE_CURRENCY_ADDRESS = 'EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c'

UPDATES_COOLDOWN = 90 if _RUNNING_MODE else 20
GECKO_TERMINAL_MAX_REQUESTS_PER_CYCLE = 20 if _RUNNING_MODE else 5

MINUTE = 60
HOUR = MINUTE * 60
NOTIFICATIONS_USER_WALLET_CHANGE_BOUND = 0.05
NOTIFICATIONS_PUMP_COOLDOWN = HOUR * 2

TELEGRAM_MESSAGE_MAX_LEN = 3700  # the actual limit is lower than 4096

BLACKLIST_TELEGRAM_ID = {}

COMMAND_START = 'start'
_COMMAND_START_DESCRIPTION = 'Subscribe to growing pool updates'
COMMAND_START_MESSAGE = 'You\'ve subscribed to growing pool updates'

COMMAND_HELP = 'help'
_COMMAND_HELP_DESCRIPTION = 'How to use bot'
COMMAND_HELP_MESSAGE = '''
Bot has 3 types of messages:

1. Pinned message - edited on every update cycle. It shows growing pools.

2. Alert - sends a message after every pump.

3. Alert for user wallet - sends a message after evey dump or pump with user tokens.
'''

COMMAND_RESEND = 'resend'
_COMMAND_RESEND_DESCRIPTION = 'Send the pinned message again'

COMMAND_MENU = [
    (f'/{COMMAND_START}', _COMMAND_START_DESCRIPTION),
    (f'/{COMMAND_HELP}', _COMMAND_HELP_DESCRIPTION),
    (f'/{COMMAND_RESEND}', _COMMAND_RESEND_DESCRIPTION),
]

DATABASES_DIR_PATH = 'data'
os.makedirs(DATABASES_DIR_PATH, exist_ok=True)
DATABASES_PATH_USERS = os.path.join(DATABASES_DIR_PATH, 'users.csv')

LOGGING_LEVEL = logging.INFO
LOGGING_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOGGING_DIR_PATH = 'logs'
os.makedirs(LOGGING_DIR_PATH, exist_ok=True)
LOGGING_PATH_WARNINGS = os.path.join(LOGGING_DIR_PATH, 'warnings.log')
LOGGING_PATH_DEBUG = os.path.join(LOGGING_DIR_PATH, 'debug.log')

TELEGRAM_FORBIDDEN_BLOCK = 'Forbidden: bot was blocked by the user'
TELEGRAM_BAD_REQUEST_MESSAGE_IS_TOO_LONG = 'Message is too long'
TELEGRAM_BAD_REQUEST_MESSAGE_IS_NOT_MODIFIED = 'Message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message'
