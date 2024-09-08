from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Self

from dex_sonar.auxiliary.time import Timedelta, Timestamp
from .ticks import Price, Tick


Change = float
Timeframe = Timedelta
Ticks = Iterable[Tick]


@dataclass
class Segment:
    timestamps: list[Timestamp]
    prices: list[Price]

    def __post_init__(self):
        self.change = self.prices[-1] / self.prices[0] - 1

    def __add__(self, other: Self):
        return (
            Segment(self.timestamps + other.timestamps, self.prices + other.prices)
            if self.get_start_timestamp() < other.get_start_timestamp() else
            Segment(other.timestamps + self.timestamps, other.prices + self.prices)
        )

    def get_start_timestamp(self) -> Timestamp:
        return self.timestamps[0]

    def get_end_timestamp(self) -> Timestamp:
        return self.timestamps[-1]

    def get_timeframe(self) -> Timeframe:
        return self.timestamps[-1] - self.timestamps[0]

    def get_magnitude(self):
        return abs(self.change)

    def get_start_index(self, ticks: Ticks):
        return next(i for i, x in enumerate(ticks) if x.timestamp == self.get_start_timestamp())

    def get_end_index(self, ticks: Ticks):
        return next(i for i, x in enumerate(ticks) if x.timestamp == self.get_end_timestamp())

    def is_upward(self):
        return self.change > 0

    def has_same_direction_as(self, other: Self):
        return self.change * other.change >= 0

    def find_right_subset_that_fit(self, min_timeframe: Timeframe | None, max_timeframe: Timeframe, min_change: Change) -> Self | None:
        for i, start_timestamp, start_price in enumerate(zip(self.timestamps, self.prices)):
            timeframe = self.timestamps[-1] - start_timestamp

            if timeframe <= max_timeframe:
                if min_timeframe and timeframe < min_timeframe:
                    return None
                else:
                    change = self.prices[-1] / start_price - 1

                    if change * min_change >= 0 and abs(change) >= abs(min_change):
                        return Segment(self.timestamps[i:], self.prices[i:])

        return None


class Segments(list[Segment]):
    def __init__(self, ticks_or_segments: Iterable[Tick] | Self, reverse_traversal=False):
        super().__init__()

        self.segments: deque[Segment] = deque(
            (
                Segment(
                    timestamps=[a.timestamp, b.timestamp],
                    prices=[a.price, b.price],
                )
                for a, b in zip(
                    ticks_or_segments[:-1],
                    ticks_or_segments[1:],
                )
            )
            if not isinstance(ticks_or_segments, Segments) else
            ticks_or_segments
        )

        if reverse_traversal:
            self.segments.reverse()

        i = 0
        while i + 2 < len(self.segments):
            s1, s2, s3 = self.segments[i], self.segments[i + 1], self.segments[i + 2]
            replacement_done = False

            if s1.has_same_direction_as(s2):
                self._replace_by_concatenation(i, s1, s2)
                replacement_done = True

            elif s2.has_same_direction_as(s3):
                self._replace_by_concatenation(i + 1, s2, s3)
                replacement_done = True

            elif self._can_be_absorbed(s1, s2, s3):
                self._replace_by_concatenation(i, s1, s2, s3)
                replacement_done = True

            if replacement_done:
                i = max(i - 2, 0)
                continue

            i += 1

        if len(self.segments) == 2:
            s1, s2 = self.segments[i], self.segments[i + 1]
            if s1.has_same_direction_as(s2): self._replace_by_concatenation(0, s1, s2)

        if reverse_traversal:
            self.segments.reverse()

        self.extend(self.segments)
        self.segments.clear()

    def _replace_by_concatenation(self, i, *segments):
        for x in segments: self.segments.remove(x)
        self.segments.insert(i, sum(segments[1:], start=segments[0]))

    @staticmethod
    def _can_be_absorbed(left: Segment, middle: Segment, right: Segment):
        return (
                left.has_same_direction_as(right) and not left.has_same_direction_as(middle) and
                middle.get_magnitude() <= min(left.get_magnitude(), right.get_magnitude())
        )

    def __repr__(self):
        segments = []

        for x in self.segments:
            segments.append(
                f'{x.get_start_timestamp().strftime("%m-%d %H:%M")}: {x.change:7.1%}'
            )

        return (
                type(self).__name__ +
                '(\n    ' +
                (
                    '\n    '.join(segments)
                    if len(self.segments) <= 50
                    else f'total: {len(self.segments)}'
                ) +
                '\n)'
        )


class SegmentsViews(Enum):
    DEFAULT = None

    def generate(self, ticks_or_segments: Ticks | Segments, reverse_traversal=False) -> Segments:
        return Segments(ticks_or_segments, reverse_traversal=reverse_traversal)

    @staticmethod
    def generate_all(ticks_or_segments: Ticks | Segments, reverse_traversal=False) -> list[Segments]:
        accumulator = []

        for segments_view in SegmentsViews:
            accumulator.append(
                segments_view.generate(
                    ticks_or_segments if not accumulator else accumulator[-1],
                    reverse_traversal=reverse_traversal
                )
            )

        return accumulator
