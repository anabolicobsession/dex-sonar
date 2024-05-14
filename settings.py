import os
import logging

_DEVELOPMENT_MODE = True
_RUNNING_MODE = not _DEVELOPMENT_MODE

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TON_API_KEY = os.environ.get('TON_API_KEY')
DEVELOPER_CHAT_ID = int(os.environ.get('DEVELOPER_TELEGRAM_ID'))

NETWORK = 'ton'
NETWORK_NATIVE_CURRENCY_ADDRESS = 'EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c'

UPDATES_COOLDOWN = 90 if _RUNNING_MODE else 20
GECKO_TERMINAL_MAX_REQUESTS_PER_CYCLE = 20 if _RUNNING_MODE else 5

MINUTE = 60
HOUR = MINUTE * 60
NOTIFICATIONS_USER_WALLET_CHANGE_BOUND = 0.05
NOTIFICATIONS_PUMP_COOLDOWN = HOUR * 2

TELEGRAM_MESSAGE_MAX_LEN = 3700
TELEGRAM_MESSAGE_MAX_WIDTH = 36

BLACKLIST_CHAT_ID = {}

COMMAND_HELP = 'help'
_COMMAND_HELP_DESCRIPTION = 'How the bot works'
COMMAND_HELP_MESSAGE = '''
This bot sends updates on potentially growing pools.

The pinned message shows all pools that have at least some sort of growth right now, sorted by growth potential. This message is getting updated every few minutes. The precise time of update can be seen in the bottom of the message.

Spontaneous messages with notification indicate fast growing pools right now. In other words, they signalize a pump. If you connect your wallet, those messages will also show dump of your jettons in addition to pump. As well as your balance of this token in TON.

The bot often gets shut down because of no hosting. You can see if bot is currently running by checking the latest update time in pinned message. If it is too old (more than five minute outdated), then the bot is probably turned off.

For feedback and new ideas contact the developer.
'''

COMMAND_START = 'start'
_COMMAND_START_DESCRIPTION = 'Subscribe to growing pool updates'
COMMAND_START_MESSAGE = 'You\'ve subscribed to growing pool updates'

COMMAND_RESEND = 'resend'
_COMMAND_RESEND_DESCRIPTION = 'Send the pinned message again'

COMMAND_MENU = [
    (f'/{COMMAND_HELP}', _COMMAND_HELP_DESCRIPTION),
    (f'/{COMMAND_START}', _COMMAND_START_DESCRIPTION),
    (f'/{COMMAND_RESEND}', _COMMAND_RESEND_DESCRIPTION),
]

DATABASES_DIR_PATH = 'data'
os.makedirs(DATABASES_DIR_PATH, exist_ok=True)
DATABASES_PATH_USERS = os.path.join(DATABASES_DIR_PATH, 'users.csv' if _RUNNING_MODE else 'development.csv')

LOGGING_LEVEL = logging.INFO
LOGGING_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOGGING_DIR_PATH = 'logs'
os.makedirs(LOGGING_DIR_PATH, exist_ok=True)
LOGGING_PATH_WARNINGS = os.path.join(LOGGING_DIR_PATH, 'warnings.log')
LOGGING_PATH_DEBUG = os.path.join(LOGGING_DIR_PATH, 'debug.log')

TELEGRAM_FORBIDDEN_BLOCK = 'Forbidden: bot was blocked by the user'
TELEGRAM_BAD_REQUEST_MESSAGE_IS_TOO_LONG = 'Message is too long'
TELEGRAM_BAD_REQUEST_MESSAGE_IS_NOT_MODIFIED = 'Message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message'
TELEGRAM_MESSAGE_TO_EDIT_NOT_FOUND = 'telegram.error.BadRequest: Message to edit not found'
