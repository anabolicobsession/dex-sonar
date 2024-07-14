import logging

from ton_sonar.network.network import Network


PRODUCTION_MODE = True
PRODUCTION_BOT = True
PRODUCTION_BOT = PRODUCTION_MODE & PRODUCTION_BOT

DATABASE_NAME_MUTELISTS = 'mutelists' if PRODUCTION_MODE else '_mutelists'
DATABASE_NAME_USERS = 'users' if PRODUCTION_MODE else '_users'

NETWORK = Network.TON

TELEGRAM_MESSAGE_MAX_LEN = 3700
TELEGRAM_MESSAGE_MAX_WIDTH = 35

LOGGING_LEVEL = logging.DEBUG
LOGGING_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

TELEGRAM_FORBIDDEN_BLOCK = 'Forbidden: bot was blocked by the user'
TELEGRAM_BAD_REQUEST_MESSAGE_IS_TOO_LONG = 'Message is too long'
TELEGRAM_BAD_REQUEST_MESSAGE_IS_NOT_MODIFIED = 'Message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message'
TELEGRAM_MESSAGE_TO_EDIT_NOT_FOUND = 'Message to edit not found'
TELEGRAM_CHAT_NOT_FOUND = 'Chat not found'
