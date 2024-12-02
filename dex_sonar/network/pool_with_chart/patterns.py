from dataclasses import dataclass
from enum import Enum
from typing import Callable, ForwardRef, Generator, Iterable

from dex_sonar.auxiliary.time import Timestamp
from dex_sonar.config.config import TESTING_MODE, config
from .change_functions import ChangeFunction
from .segments import Change, Segment, Segments, SegmentsViews, Timeframe
from .ticks import Tick
from ..network import Pool


Magnitude = Change


@dataclass
class Match:
    is_first_order: bool


@dataclass
class SegmentPattern:

    min_change_fun: ChangeFunction
    min_timeframe: Timeframe = None
    max_timeframe: Timeframe = None

    is_magnitude_indicator: bool = False
    can_be_right_subset: bool = False

    def __post_init__(self):
        self.min_change_fun = staticmethod(self.min_change_fun)

    def get_match(self, segment: Segment, pool: Pool) -> Match | None:
        timeframe = segment.get_timeframe()

        if (
                self.min_timeframe and timeframe < self.min_timeframe or
                self.max_timeframe and timeframe > self.max_timeframe
        ):
            if self.can_be_right_subset and self.max_timeframe and self.max_timeframe and timeframe > self.max_timeframe:
                min_change, min_change_second_order = self.min_change_fun(timeframe, pool)

                if self._does_satisfy(segment, min_change) and segment.find_right_subset_that_fit(self.min_timeframe, self.max_timeframe, min_change):
                    return Match(is_first_order=True)

                elif self._does_satisfy(segment, min_change_second_order) and segment.find_right_subset_that_fit(self.min_timeframe, self.max_timeframe, min_change_second_order):
                    return Match(is_first_order=False)

            return None

        else:
            min_change, min_change_second_order = self.min_change_fun(timeframe, pool)

            if min_change and self._does_satisfy(segment, min_change):
                return Match(is_first_order=True)

            elif min_change_second_order and self._does_satisfy(segment, min_change_second_order):
                return Match(is_first_order=False)

            else:
                return None

    @staticmethod
    def _does_satisfy(segment: Segment, min_change: Change):
        return segment.change * min_change >= 0 and segment.get_magnitude() >= abs(min_change)


class SegmentsPattern(list[SegmentPattern]):
    def __init__(self, *segment_patterns: SegmentPattern):
        super().__init__(segment_patterns)

        self.magnitude_indicator_index = 0

        for i, sp in enumerate(self):

            if sp.is_magnitude_indicator:
                self.magnitude_indicator_index = i

            if sp.can_be_right_subset and i > 0:
                sp.can_be_right_subset = False

    def get_magnitude_indicator_index(self):
        return self.magnitude_indicator_index


class Patterns(Enum):

    DUMP = SegmentsPattern(
        SegmentPattern(
            min_change_fun=(
                lambda tf, p:
                (None, None)
            ),
            max_timeframe=Timeframe(minutes=10),
            can_be_right_subset=True,
        )
    )
    

# Significance = bool


@dataclass
class _PatternMatchBody:
    start_timestamp: Timestamp
    end_timestamp: Timestamp
    significant: Significance
    magnitude: Magnitude


class _PatternBody:
    def __init__(self, *units: SegmentPattern, significance_threshold: float = None):
        self.units = units
        self.length = len(units)
        self.significance_threshold = significance_threshold / 100 if significance_threshold else None
        self.magnitude_index = max(enumerate(units), key=lambda x: x[1].get_min_magnitude())[0]

    def _match(self, trends_slice, pool):
        return all([
            x.get_match(y, pool) for x, y in zip(
                self.units,
                trends_slice,
            )
        ])

    def _extract_info(self, trends: SegmentsSlice) -> tuple[Significance, Magnitude]:
        magnitude = trends[self.magnitude_index].get_magnitude()
        pattern_magnitude = self.units[self.magnitude_index].get_min_magnitude()
        ratio = magnitude / pattern_magnitude
        return (
            trends[0].start_timestamp,
            trends[-1].end_timestamp,
            True if not self.significance_threshold else ratio >= self.significance_threshold,
            magnitude,
        )

    def match(
            self,
            trends: Segments,
            pool: Pool,
            delay_tolerance: Timeframe = None,
    ) -> _PatternMatchBody | None:

        if (
                len(trends) >= self.length
        ):
            trends_slice = trends[-self.length:]

            if self._match(trends_slice, pool):
                return _PatternMatchBody(*self._extract_info(trends_slice))

        if (
                delay_tolerance and
                len(trends) - 1 >= self.length and
                trends[-1].get_timeframe() <= delay_tolerance
        ):
            trends_slice = trends[-self.length - 1:-1]

            if self._match(trends_slice, pool):
                return _PatternMatchBody(*self._extract_info(trends_slice))

        return None


_Pattern = ForwardRef('Pattern')





class PatternMatch(_PatternMatchBody):
    def __init__(self, pattern: _Pattern, body: _PatternMatchBody):
        self.pattern = pattern
        super().__init__(body.start_timestamp, body.end_timestamp, body.significant, body.magnitude)


class PatternOld(Enum):

    DUMP = _PatternBody(
        SegmentPattern(
            -8,
            max_timeframe=Timeframe(minutes=10)
        ),
    )

    DOWNTREND = _PatternBody(
        SegmentPattern(
            -30,
            max_timeframe=Timeframe(hours=2)
        ),
        significance_threshold=100000,
    )

    REVERSAL = _PatternBody(
        SegmentPattern(
            -30,
            min_timeframe=Timeframe(hours=2)
        ),
        SegmentPattern(
            10,
            min_timeframe=Timeframe(minutes=30)
        ),
        significance_threshold=100000,
    )


    PUMP = _PatternBody(
        SegmentPattern(
            50,
            max_timeframe=Timeframe(hours=1)
        ),
        significance_threshold=100000,
    )

    UPTREND = _PatternBody(
        SegmentPattern(
            20,
            min_timeframe=Timeframe(hours=2)
        ),
        significance_threshold=100000,
    )

    SLOW_UPTREND = _PatternBody(
        SegmentPattern(
            10,
            min_timeframe=Timeframe(hours=12)
        ),
        significance_threshold=100000,
    )


    def get_name(self):
        return self.name.replace('_', ' ').title()

    def get_abbreviation(self):
        if self is PatternOld.DOWNTREND: return 'DW'
        if self is PatternOld.SLOW_UPTREND: return 'SU'
        return self.name[0]

    def match(self, ticks: Iterable[Tick], pool: Pool = None) -> Generator[PatternMatch, None, None]:

        trends_views = SegmentsViews.generate_all(ticks)

        for trends in trends_views:
            if match_body := self.value.match(trends, pool, delay_tolerance=Timeframe(minutes=config.getint('Patterns', 'delay_tolerance'))):
                yield PatternMatch(self, match_body)

    @staticmethod
    def match_any(ticks: Iterable[Tick], pool: Pool = None, reverse_trends_views_traversal=False) -> Generator[PatternMatch, None, None]:

        trends_views = SegmentsViews.generate_all(ticks)
        if reverse_trends_views_traversal: trends_views = list(reversed(trends_views))

        for pattern in PatternOld:

            for trends in trends_views:

                if match_body := pattern.value.match(trends, pool, delay_tolerance=Timeframe(minutes=config.getint('Patterns', 'delay_tolerance'))):
                    yield PatternMatch(pattern, match_body)
