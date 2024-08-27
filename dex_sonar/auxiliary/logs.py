import logging
from logging import Formatter, LogRecord, StreamHandler, getLogger
from math import floor
from statistics import mean

import colorama
from colorama import Fore

from dex_sonar.auxiliary.time import Timestamp
from dex_sonar.config.config import LOGGING_FORMAT, LOGGING_LEVEL, LOGGING_TIMESTAMP_FORMAT


Color = str
VERBOSE = floor(mean([logging.DEBUG, logging.INFO]))


def verbose(self, msg, *args, **kwargs):
    if self.isEnabledFor(VERBOSE):
        self._log(VERBOSE, msg, args, **kwargs)


class ColoredFormatter(Formatter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def format(self, record: LogRecord):
        return {
            logging.DEBUG:    Fore.BLUE,
            VERBOSE:          Fore.MAGENTA,
            logging.INFO:     Fore.BLACK,
            logging.WARNING:  Fore.YELLOW,
            logging.ERROR:    Fore.RED,
            logging.CRITICAL: Fore.RED,
        }[record.levelno] + super().format(record)


def setup_logging():
    logging.Formatter.converter = lambda *args: Timestamp.now().timetuple()

    colorama.init(autoreset=True)
    logging.addLevelName(VERBOSE, 'VERBOSE')
    logging.Logger.verbose = verbose

    root_logger = getLogger()
    root_logger.setLevel(level=LOGGING_LEVEL)

    handler = StreamHandler()
    handler.setLevel(LOGGING_LEVEL)
    handler.setFormatter(ColoredFormatter(LOGGING_FORMAT, datefmt=LOGGING_TIMESTAMP_FORMAT))
    root_logger.addHandler(handler)

    getLogger('asyncio').setLevel(logging.WARNING)
    getLogger('telegram').setLevel(logging.WARNING)
    getLogger('httpx').setLevel(logging.WARNING)
    getLogger('httpcore').setLevel(logging.INFO)
    getLogger('matplotlib').setLevel(logging.INFO)
