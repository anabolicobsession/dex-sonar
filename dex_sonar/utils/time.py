import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Self

from dex_sonar.config.config import TIMEZONE


Seconds = float


@dataclass
class TimeUnit:
    in_seconds: Seconds
    name: str

    def to_string(self, seconds: Seconds):
        units = math.floor(seconds / self.in_seconds)
        name = self.name if units < 2 else self.name + 's'
        return f'{units} {name}'


class Timedelta(timedelta):

    SECOND = TimeUnit(
        1,
        'sec',
    )

    MINUTE = TimeUnit(
        SECOND.in_seconds * 60,
        'min',
    )

    HOUR = TimeUnit(
        MINUTE.in_seconds * 60,
        'hour',
    )

    DAY = TimeUnit(
        HOUR.in_seconds * 24,
        'day',
    )

    MONTH = TimeUnit(
        DAY.in_seconds * 30,
        'month',
    )

    YEAR = TimeUnit(
        MONTH.in_seconds * 365,
        'year',
    )

    TIME_UNITS = [
        SECOND,
        MINUTE,
        HOUR,
        DAY,
        MONTH,
        YEAR,
    ]

    @classmethod
    def from_other(cls, other: timedelta) -> Self:
        return cls(
            days=other.days,
            seconds=other.seconds,
            microseconds=other.microseconds,
        )

    def positive_difference(self, other: timedelta) -> Self:
        return max(self - other, Timedelta())

    def to_human_readable_format(self):
        seconds = self.total_seconds()

        for i in range(len(self.TIME_UNITS) - 1):

            time_unit = self.TIME_UNITS[i]
            next_time_unit = self.TIME_UNITS[i + 1]

            if seconds < next_time_unit.in_seconds:
                return time_unit.to_string(seconds)

    def __add__(self, other: timedelta) -> Self:
        return self.from_other(super().__add__(other))

    __radd__ = __add__

    def __sub__(self, other: timedelta) -> Self:
        return self.from_other(super().__sub__(other))

    def __rsub__(self, other: timedelta) -> Self:
        return self.from_other(super().__rsub__(other))


class Timestamp(datetime):
    @classmethod
    def from_other(cls, other: datetime):
        return Timestamp(
            year=other.year,
            month=other.month,
            day=other.day,
            hour=other.hour,
            minute=other.minute,
            second=other.second,
            microsecond=other.microsecond,
            tzinfo=other.tzinfo,
        )

    @classmethod
    def now(cls, tz=TIMEZONE) -> Self:
        return cls.from_other(super().now(tz))

    @classmethod
    def now_in_seconds(cls, tz=TIMEZONE) -> Seconds:
        return super().now(tz).timestamp()

    def time_elapsed(self, tz=TIMEZONE) -> Timedelta:
        return self.now(tz) - self

    def time_elapsed_in_seconds(self, tz=TIMEZONE) -> Seconds:
        return (self.now(tz) - self).total_seconds()

    def time_left(self, tz=TIMEZONE) -> Timedelta:
        return self.positive_difference(self.now(tz))

    def time_left_in_seconds(self, tz=TIMEZONE) -> Seconds:
        return self.positive_difference(self.now(tz)).total_seconds()

    def positive_difference(self, other: datetime) -> Timedelta:
        return max(self - other, Timedelta())

    def __add__(self, other: timedelta) -> Self:
        return self.from_other(super().__add__(other))

    __radd__ = __add__

    def __sub__(self, other: datetime | timedelta) -> Self | Timedelta:
        object = super().__sub__(other)
        return self.from_other(object) if isinstance(object, datetime) else Timedelta.from_other(object)


class Cooldown:
    def __init__(
            self,
            cooldown: Timedelta,
            multiplier: float = 1,
            within_time_period: Timedelta = None
    ):
        self.start_cooldown = cooldown.total_seconds()
        self.cooldown = self.start_cooldown
        self.multiplier = multiplier

        self.auto_reset_after = within_time_period.total_seconds() if within_time_period else None
        self.last_timestamp = None

    def reset(self, only_if_no_auto_reset=False):
        if only_if_no_auto_reset and self.auto_reset_after:
            return
        self.cooldown = self.start_cooldown

    def get(self) -> Seconds:
        if (
                self.auto_reset_after and
                self.last_timestamp and
                (Timestamp.now_in_seconds() - self.last_timestamp) > self.auto_reset_after
        ):
            self.cooldown = self.start_cooldown
        return self.cooldown

    def make(self) -> Seconds:
        cooldown = self.get()
        self.cooldown *= self.multiplier
        self.last_timestamp = Timestamp.now_in_seconds()
        return cooldown
