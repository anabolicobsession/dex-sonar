from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Self

from dex_sonar.auxiliary.time import Timedelta, Timestamp
from .ticks import Price, Tick


Timeframe = Timedelta


@dataclass
class Segment:
    start_timestamp: Timestamp
    end_timestamp: Timestamp
    prices: list[Price]

    def __post_init__(self):
        self.normalized_change = self.prices[-1] / self.prices[0] - 1

    def is_upward(self):
        return self.normalized_change > 0

    def is_codirectional_with(self, other: Self):
        return self.normalized_change * other.normalized_change >= 0

    def get_timeframe(self) -> Timedelta:
        return self.end_timestamp - self.start_timestamp

    def get_magnitude(self):
        return abs(self.normalized_change)

    def get_start_index(self, ticks: Iterable[Tick]):
        return next(i for i, x in enumerate(ticks) if x.timestamp == self.start_timestamp)

    def get_end_index(self, ticks: Iterable[Tick]):
        return next(i for i, x in enumerate(ticks) if x.timestamp == self.end_timestamp)

    def __add__(self, other):
        return Segment(self.start_timestamp, other.end_timestamp, self.prices + other.prices)


SegmentsSlice = list[Segment]


class Segments:
    def __init__(self, ticks_or_segments: Iterable[Tick] | Self):
        self.segments: deque[Segment] | None = None
        self.initialize(ticks_or_segments)
        self.length = len(self.segments)

    def __len__(self):
        return len(self.segments)

    def __iter__(self):
        return iter(self.segments)

    def __getitem__(self, i: int | slice) -> Segment | SegmentsSlice:
        if isinstance(i, int):
            return self.segments[i]
        else:
            start = i.start if i.start is not None else 0
            stop  = i.stop  if i.stop  is not None else self.length
            step  = i.step  if i.step  is not None else 1

            start = start % self.length
            if stop != self.length: stop = stop % self.length

            return [self.segments[j] for j in range(start, stop, step)]

    def slice_itself(self, s: slice) -> Self:
        new = deepcopy(self)
        new.segments = deque(self[s])
        return new

    def __repr__(self):
        trends = []

        for x in self.segments:
            trends.append(
                f'{x.start_timestamp.strftime("%m-%d %H:%M")}: {x.normalized_change:7.1%}'
            )

        return (
                type(self).__name__ +
                '(\n    ' +
                (
                    '\n    '.join(trends)
                    if len(self.segments) <= 50
                    else f'total: {len(self.segments)}'
                ) +
                '\n)'
        )

    def initialize(self, ticks_or_trends):
        if not isinstance(ticks_or_trends, Segments):
            prices = [x.price for x in ticks_or_trends]
            timestamps = [x.timestamp for x in ticks_or_trends]
            changes = [
                (y - x) / x if x else 0 for x, y in zip(
                    prices[:-1],
                    prices[1:],
                )
            ]
            self.segments = deque(
                Segment(x, y, z) for x, y, z in zip(
                    changes,
                    timestamps[:-1],
                    timestamps[1:],
                )
            )
        else:
            self.segments = deepcopy(ticks_or_trends.segments)

        self.segments.reverse()

        i = 0
        while i + 2 < len(self.segments):
            t1, t2, t3 = self.segments[i], self.segments[i + 1], self.segments[i + 2]
            replacement_done = False

            if t1.is_codirectional_with(t2) and self._are_within_limits(t1, t2):
                self._replace_by_concatenation(i, t1, t2)
                replacement_done = True

            elif t2.is_codirectional_with(t3) and self._are_within_limits(t2, t3):
                self._replace_by_concatenation(i + 1, t2, t3)
                replacement_done = True

            elif self._can_be_absorbed(t1, t2, t3) and self._are_within_limits(t1, t2, t3):
                self._replace_by_concatenation(i, t1, t2, t3)
                replacement_done = True

            if replacement_done:
                i = max(i - 2, 0)
                continue

            i += 1

        if len(self.segments) == 2:
            t1, t2 = self.segments[i], self.segments[i + 1]

            if t1.is_codirectional_with(t2) and self._are_within_limits(t1, t2):
                self._replace_by_concatenation(0, t1, t2)

        self.segments.reverse()

    @staticmethod
    def _concatenate(trends):
        return sum(trends[1:], start=trends[0])

    def _replace_by_concatenation(self, i, *trends):
        for x in trends:
            self.segments.remove(x)
        self.segments.insert(i, self._concatenate(trends))

    def _are_within_limits(self, *trends):
        x = self._concatenate(trends)
        if self.max_timeframe and x.get_timeframe() > self.max_timeframe: return False
        if self.max_magnitude and x.get_magnitude() > self.max_magnitude: return False
        return True

    @staticmethod
    def _can_be_absorbed(left, middle, right):
        return (
                left.is_codirectional_with(right) and not left.is_codirectional_with(middle) and
                middle.get_magnitude() <= min(left.get_magnitude(), right.get_magnitude())
        )


@dataclass
class _TrendsViewValue:
    max_timeframe: Timeframe = None
    max_magnitude: float = None

    def __post_init__(self):
        if self.max_magnitude: self.max_magnitude /= 100


class TrendsView(Enum):

    TIMEFRAME_10M = _TrendsViewValue(
        max_timeframe=Timeframe(minutes=10),
    )

    TIMEFRAME_15M = _TrendsViewValue(
        max_timeframe=Timeframe(minutes=15),
    )

    TIMEFRAME_30M = _TrendsViewValue(
        max_timeframe=Timeframe(minutes=30),
    )

    GLOBAL = _TrendsViewValue()

    def generate_trends(self, ticks_or_trends: Iterable[Tick] | Segments) -> Segments:
        return Segments(ticks_or_trends, max_timeframe=self.value.max_timeframe, max_magnitude=self.value.max_magnitude)

    @staticmethod
    def generate_all(ticks_or_trends: Iterable[Tick] | Segments) -> list[Segments]:
        accumulator = []

        for trends_view in TrendsView:
            accumulator.append(
                trends_view.generate_trends(
                    ticks_or_trends if not accumulator else accumulator[-1]
                )
            )

        return accumulator
