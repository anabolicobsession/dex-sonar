from dataclasses import dataclass
from enum import Enum
from typing import ForwardRef, Generator, Iterable

from dex_sonar.auxiliary.time import Timedelta, Timestamp
from dex_sonar.config.config import TESTING_MODE, config
from .segments import Segment, Segments, SegmentsSlice, TrendsView
from .ticks import Tick
from ..network import Pool as NetworkPool


Timeframe = Timedelta
Significance = bool
Magnitude = float


@dataclass
class PatternUnit:
    min_change: float
    min_timeframe: Timeframe = None
    max_timeframe: Timeframe = None

    def __post_init__(self):
        self.min_change /= 100

    def get_magnitude(self):
        return abs(self.min_change)

    @staticmethod
    def _have_same_sign(a, b):
        return a * b >= 0

    @staticmethod
    def _scale(x, pool: NetworkPool = None, base=100_000, slope=2.5):
        if TESTING_MODE:
            return x / 10
        if pool and pool.liquidity and pool.liquidity < base:
            deviation = (base - pool.liquidity) / base
            return x * (1 + slope * deviation)
        return x

    def match(self, trend: Segment, pool: NetworkPool):
        return (
                self._have_same_sign(self.min_change, trend.normalized_change) and trend.get_magnitude() >= self._scale(self.get_magnitude(), pool) and
                not (self.min_timeframe and trend.get_timeframe() < self.min_timeframe) and
                not (self.max_timeframe and trend.get_timeframe() > self.max_timeframe)
        )


@dataclass
class _PatternMatchBody:
    start_timestamp: Timestamp
    end_timestamp: Timestamp
    significant: Significance
    magnitude: Magnitude


class _PatternBody:
    def __init__(self, *units: PatternUnit, significance_threshold: float = None):
        self.units = units
        self.length = len(units)
        self.significance_threshold = significance_threshold / 100 if significance_threshold else None
        self.magnitude_index = max(enumerate(units), key=lambda x: x[1].get_magnitude())[0]

    def _match(self, trends_slice, pool):
        return all([
            x.match(y, pool) for x, y in zip(
                self.units,
                trends_slice,
            )
        ])

    def _extract_info(self, trends: SegmentsSlice) -> tuple[Significance, Magnitude]:
        magnitude = trends[self.magnitude_index].get_magnitude()
        pattern_magnitude = self.units[self.magnitude_index].get_magnitude()
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
            pool: NetworkPool,
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


class Pattern(Enum):

    DUMP = _PatternBody(
        PatternUnit(
            -8,
            max_timeframe=Timeframe(minutes=10)
        ),
    )

    DOWNTREND = _PatternBody(
        PatternUnit(
            -30,
            max_timeframe=Timeframe(hours=2)
        ),
        significance_threshold=100000,
    )

    REVERSAL = _PatternBody(
        PatternUnit(
            -30,
            min_timeframe=Timeframe(hours=2)
        ),
        PatternUnit(
            10,
            min_timeframe=Timeframe(minutes=30)
        ),
        significance_threshold=100000,
    )


    PUMP = _PatternBody(
        PatternUnit(
            50,
            max_timeframe=Timeframe(hours=1)
        ),
        significance_threshold=100000,
    )

    UPTREND = _PatternBody(
        PatternUnit(
            20,
            min_timeframe=Timeframe(hours=2)
        ),
        significance_threshold=100000,
    )

    SLOW_UPTREND = _PatternBody(
        PatternUnit(
            10,
            min_timeframe=Timeframe(hours=12)
        ),
        significance_threshold=100000,
    )


    def get_name(self):
        return self.name.replace('_', ' ').title()

    def get_abbreviation(self):
        if self is Pattern.DOWNTREND: return 'DW'
        if self is Pattern.SLOW_UPTREND: return 'SU'
        return self.name[0]

    def match(self, ticks: Iterable[Tick], pool: NetworkPool = None) -> Generator[PatternMatch, None, None]:

        trends_views = TrendsView.generate_all(ticks)

        for trends in trends_views:
            if match_body := self.value.match(trends, pool, delay_tolerance=Timeframe(minutes=config.getint('Patterns', 'delay_tolerance'))):
                yield PatternMatch(self, match_body)

    @staticmethod
    def match_any(ticks: Iterable[Tick], pool: NetworkPool = None, reverse_trends_views_traversal=False) -> Generator[PatternMatch, None, None]:

        trends_views = TrendsView.generate_all(ticks)
        if reverse_trends_views_traversal: trends_views = list(reversed(trends_views))

        for pattern in Pattern:

            for trends in trends_views:

                if match_body := pattern.value.match(trends, pool, delay_tolerance=Timeframe(minutes=config.getint('Patterns', 'delay_tolerance'))):
                    yield PatternMatch(pattern, match_body)
