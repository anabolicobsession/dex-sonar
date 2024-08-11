from __future__ import annotations

import logging
from abc import ABC
from asyncio import sleep
from enum import Enum
from typing import Any, Type

from aiohttp import ClientSession

from dex_sonar.api.request_limits import RateLimitExceeded, RateLimiter, RequestLimits
from dex_sonar.utils.time import Cooldown, Timedelta, Timestamp


logger = logging.getLogger(__name__)


JSON = dict[str, Any]
Code = int
Message = str


class NotDefinedConstant(Exception):
    def __init__(self):
        super().__init__(
            'Inherited class must redefine all the parent constants'
        )


class UnexpectedResponse(Exception):
    def __init__(self, code, message, text=None):
        super().__init__(
            f'{code} / {message}{"" if not text else ": " + text}'
        )


class InternalServerError(Exception):
    ...


class UnsupportedSchema(Exception):
    def __init__(self, supported_schema_version, got_schema_version):
        super().__init__(
            f'Supported version: {supported_schema_version}, got: {got_schema_version}'
        )


class EmptyData(Exception):
    ...


class Status(Enum):
    OK = 200
    RATE_LIMIT_EXCEEDED = 429
    INTERNAL_SERVER_ERROR = 500

    def get_message(self):
        return {
            Status.OK: 'OK',
            Status.RATE_LIMIT_EXCEEDED: 'Too Many Requests',
            Status.INTERNAL_SERVER_ERROR: 'Internal Server Error',
        }[self]

    @staticmethod
    def create_from(code: Code, message: Message) -> Status | None:
        for status in Status:
            if status.value == code and status.get_message() == message:
                return status
        return None


class API(ABC):

    NAME: str = None
    REQUEST_LIMITS: RequestLimits = None
    RATE_LIMITER_TYPE: Type[RateLimiter] = None

    URL_PATH_SEPARATOR = '/'
    HEADERS = {'cache-control': 'max-age=0'}

    def __init__(
            self,
            base_url: str,
            request_error_cooldown: Cooldown | None = None,
            raise_on_rate_limit=False,
    ):
        if not all([self.NAME, self.REQUEST_LIMITS, self.RATE_LIMITER_TYPE]):
            raise NotDefinedConstant()

        self.base_url = base_url
        self.rate_limiter: RateLimiter = self.RATE_LIMITER_TYPE(self.REQUEST_LIMITS, raise_on_rate_limit)
        self.error_cooldown = request_error_cooldown
        self.session = None

    def get_available_requests(self):
        return self.rate_limiter.get_available_requests()

    def get_time_until_new_requests_can_be_made(self, number_of_requests=None) -> Timedelta:
        return self.rate_limiter.get_time_until_new_requests_can_be_made(number_of_requests)

    async def _get_json(self, *url_path_segments, **params) -> JSON:

        if not self.session:
            self.session = ClientSession()

        while True:

            async with await self.session.get(
                    url=self._form_url(*url_path_segments),
                    headers=API.HEADERS,
                    params={
                        'anti-cache': Timestamp.now_in_seconds(),
                        **params,
                    }
            ) as response:

                code, message = response.status, response.reason
                self.rate_limiter.mark_request_sending()

                match Status.create_from(code, message):

                    case Status.OK:
                        self.error_cooldown.reset(only_if_no_auto_reset=True)
                        return await response.json()

                    case Status.RATE_LIMIT_EXCEEDED:

                        if self.error_cooldown:
                            logger.warning(self._insert_name(
                                f'Rate limit exceeded. '
                                f'Waiting {round(self.error_cooldown.get()):.0f}s'
                            ))
                            await sleep(self.error_cooldown.make())
                            continue

                        else:
                            raise RateLimitExceeded(self._insert_name(
                                f'Try to make fewer requests or add cooldown'
                            ))

                    case Status.INTERNAL_SERVER_ERROR:

                        if self.error_cooldown:
                            logger.warning(self._insert_name(
                                f'Internal server error ({self.base_url})'
                                f': Waiting {round(self.error_cooldown.get()):.0f}s'
                            ))
                            await sleep(self.error_cooldown.make())
                            continue

                        else:
                            raise InternalServerError(self._insert_name())

                    case _:
                        raise UnexpectedResponse(code, message, await response.text())

    async def close(self):
        if self.session: await self.session.close()

    def _insert_name(self, string = None):
        return f'{self.NAME}: {string}' if string else self.NAME

    def _form_url(self, *path_segments):
        return API.URL_PATH_SEPARATOR.join([self.base_url, *path_segments])
