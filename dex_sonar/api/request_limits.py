from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass

from dex_sonar.utils.time import Timedelta, Timestamp


class InvalidRequestNumber(Exception):
    ...


class RateLimitExceeded(Exception):
    ...


@dataclass
class RequestLimits:
    max: int
    time_period: Timedelta

    def to_human_readable_format(self):
        return f'{self.max} / {self.time_period.to_human_readable_format()}'


class RateLimiter(ABC):
    def __init__(self, request_limits: RequestLimits, raise_exception_on_limit=False):
        self.timeline: deque[Timestamp] = deque()
        self.request_limits = request_limits
        self.raise_on_limit = raise_exception_on_limit

    def __repr__(self):
        self._clear_outdated_requests()
        properties = [f'requests: {len(self.timeline)}']

        if len(self.timeline):
            properties.append(f'time: {self.timeline[0].strftime("%H:%M:%S")}')
            if len(self.timeline) > 1: properties[-1] += f' - {self.timeline[-1].strftime("%H:%M:%S")}'

        return (
            type(self).__name__ +
            '(' +
            ', '.join(properties) +
            ')'
        )

    def mark_request_sending(self):
        if len(self.timeline) == self.request_limits.max:

            if not self.raise_on_limit:
                if len(self.timeline): self.timeline.popleft()
            else:
                raise RateLimitExceeded(self.request_limits.to_human_readable_format())

        self.timeline.append(Timestamp.now())

    def get_available_requests(self):
        self._clear_outdated_requests()
        return self.request_limits.max - len(self.timeline)

    @abstractmethod
    def get_time_until_new_requests_can_be_made(self, requests=None) -> Timedelta:
        ...

    def _clear_outdated_requests(self):
        reset_index = None

        for i, timestamp in enumerate(self.timeline):

            if timestamp.time_elapsed() > self.request_limits.time_period:
                reset_index = i
            else:
                break

        if reset_index is not None:
            for _ in range(reset_index + 1): self.timeline.popleft()

    def _get_time_needed_for_request_to_be_outdated(self, request_timestamp: Timestamp):
        outdatedness_bound = Timestamp.now() - self.request_limits.time_period
        return max(request_timestamp - outdatedness_bound, Timedelta())


class SmartRateLimiter(RateLimiter):
    def get_time_until_new_requests_can_be_made(self, requests=None) -> Timedelta:
        self._clear_outdated_requests()

        if requests:
            if requests > self.request_limits.max:
                raise InvalidRequestNumber(
                    f'Number of desired requests are higher than the limit: {requests} > {self.request_limits.max}'
                )
        else:
            requests = self.request_limits.max

        available_requests = self.get_available_requests()

        if available_requests >= requests:
            return Timedelta()
        else:
            lacking_requests = requests - available_requests
            return self._get_time_needed_for_request_to_be_outdated(
                self.timeline[lacking_requests - 1]
            )


class StrictRateLimiter(RateLimiter):
    def get_time_until_new_requests_can_be_made(self, requests=None) -> Timedelta:
        self._clear_outdated_requests()
        return self._get_time_needed_for_request_to_be_outdated(self.timeline[-1]) if self.timeline else Timedelta()
