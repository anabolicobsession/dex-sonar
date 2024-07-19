import logging
from logging import getLogger, Formatter, StreamHandler

from .config.config import LOGGING_LEVEL, LOGGING_FORMAT


def setup_logging():
    root_logger = getLogger()
    root_logger.setLevel(level=LOGGING_LEVEL)

    handler = StreamHandler()
    handler.setLevel(LOGGING_LEVEL)
    handler.setFormatter(Formatter(LOGGING_FORMAT))
    root_logger.addHandler(handler)

    getLogger('asyncio').setLevel(logging.WARNING)
    getLogger('telegram').setLevel(logging.WARNING)
    getLogger('httpx').setLevel(logging.WARNING)
    getLogger('httpcore').setLevel(logging.INFO)
    getLogger('matplotlib').setLevel(logging.INFO)
