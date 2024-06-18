import logging
from asyncio import sleep
from copy import deepcopy
from datetime import timedelta
from enum import Enum
from typing import Any

from aiohttp import ClientSession, ClientResponseError


logger = logging.getLogger(__name__)


JSON = dict[str, Any]
Code = int
Message = str


class Status(Enum):
    OK = 200
    RATE_LIMIT_EXCEEDED = 429

    @staticmethod
    def has(code: int):
        return any(status.value == code for status in Status)

    def to_message(self):
        return {
            Status.OK: 'OK',
            Status.RATE_LIMIT_EXCEEDED: 'Too Many Requests',
        }[self]

    @staticmethod
    def are_valid(code: int, message: str):
        return Status.has(code) and Status(code).to_message() == message


Response = (JSON, Code, Message)


class Cooldown:
    Seconds = float

    def __init__(self, cooldown: timedelta, multiplier: float = 1):
        self.cooldown = cooldown
        self.multiplier = multiplier
        self.BASE_COOLDOWN = cooldown

    def get(self) -> timedelta:
        return self.cooldown

    def make(self) -> Seconds:
        base = self.cooldown
        self.cooldown *= self.multiplier
        return base.total_seconds()

    def reset(self):
        self.cooldown = self.BASE_COOLDOWN


class UnexpectedResponse(Exception):
    def __init__(self, code, message, text=None):
        super().__init__(f'{code}/{message}{"" if not text else ", " + text}')


class UnsupportedSchema(Exception):
    def __init__(self, supported_schema_version, received_schema_version):
        super().__init__(f'Supported version: {supported_schema_version}, got: {received_schema_version}')


class RateLimitExceeded(Exception):
    def __init__(self):
        super().__init__(f'Try to make fewer requests or increase a cooldown')


class EmptyData(Exception):
    ...


class BaseAPI:

    URL_PATH_SEPARATOR = '/'
    HEADERS = {'cache-control': 'max-age=0'}

    def __init__(self, base_url, cooldown: Cooldown | None = None):
        self.base_url = base_url
        self.session = ClientSession(raise_for_status=True)
        self.cooldown = cooldown

    async def close(self):
        await self.session.close()

    def _form_url(self, *path_segments):
        return BaseAPI.URL_PATH_SEPARATOR.join([self.base_url, *path_segments])

    async def _get(self, *url_path_segments, **params) -> Response:
        while True:
            try:
                response = await self.session.get(self._form_url(*url_path_segments), **params, headers=BaseAPI.HEADERS)

            except ClientResponseError as e:

                if e.status == Status.RATE_LIMIT_EXCEEDED.value and e.message == Status(e.status).to_message():
                    if self.cooldown:
                        logger.info(f'Going to sleep for {self.cooldown.get()}: {e.message}')
                        await sleep(self.cooldown.make())
                        continue
                    else:
                        raise RateLimitExceeded()
                else:
                    raise UnexpectedResponse(e.status, e.message)

            if self.cooldown:
                self.cooldown.reset()

            code, message = response.status, response.reason

            if Status.are_valid(code, message):
                json = deepcopy(await response.json())
                response.close()
                return json, code, message
            else:
                raise UnexpectedResponse(code, message, await response.text())
