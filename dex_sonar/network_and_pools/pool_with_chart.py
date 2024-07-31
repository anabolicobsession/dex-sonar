import gc
from abc import ABC
from collections import deque
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from statistics import mean
from typing import Any, ForwardRef, Generator, Iterable, Self

from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from matplotlib.dates import DateFormatter
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from dex_sonar.config.config import TESTING_MODE, config
from dex_sonar.network_and_pools.network import Pool as NetworkPool
from dex_sonar.utils.circular_list import CircularList
from dex_sonar.utils.time import Timedelta, Timestamp


Timeframe = Timedelta
Significance = bool
Magnitude = float
Pyplot = Any
Color = str

TIMESTAMP_UNIT = Timedelta(minutes=1)

plt.rcParams.update({'mathtext.default': 'regular'})


@dataclass
class _AbstractDataclass(ABC):
    def __new__(cls, *args, **kwargs):
        if cls == _AbstractDataclass or cls.__bases__[0] == _AbstractDataclass:
            raise TypeError('Can\'t instantiate an abstract class')
        return super().__new__(cls)


@dataclass
class Tick(_AbstractDataclass):
    timestamp: Timestamp
    price: float

    def __repr__(self):
        return f'{type(self).__name__}({self.timestamp.strftime("%m-%d %H:%M:%S")}, {self.price})'


@dataclass(repr=False)
class CompleteTick(Tick):
    volume: float


@dataclass(repr=False)
class IncompleteTick(Tick):
    ...


@dataclass
class Trend:
    change: float
    start_timestamp: Timestamp
    end_timestamp: Timestamp

    def is_upward(self):
        return self.change > 0

    def get_timeframe(self) -> Timedelta:
        return self.end_timestamp - self.start_timestamp

    def get_magnitude(self):
        return abs(self.change)

    def get_start_index(self, ticks: Iterable[Tick]):
        return next(i for i, x in enumerate(ticks) if x.timestamp == self.start_timestamp)

    def get_end_index(self, ticks: Iterable[Tick]):
        return next(i for i, x in enumerate(ticks) if x.timestamp == self.end_timestamp)

    def is_codirectional_with(self, other):
        return self.change * other.change >= 0

    def __add__(self, other):
        times = (self.start_timestamp, other.end_timestamp) if self.start_timestamp < other.end_timestamp else (other.start_timestamp, self.end_timestamp)
        change = (1 + self.change) * (1 + other.change) - 1
        return Trend(change, *times)


TrendsSlice = list[Trend, ...]

class Trends:
    def __init__(
            self,
            ticks_or_trends: Iterable[Tick] | Self,
            max_timeframe: Timedelta = None,
            max_magnitude: float = None,
    ):
        self.trends: deque[Trend] | None = None
        self.max_timeframe = max_timeframe
        self.max_magnitude = max_magnitude
        self.initialize(ticks_or_trends)
        self.length = len(self.trends)

    def __len__(self):
        return len(self.trends)

    def __iter__(self):
        return iter(self.trends)

    def __getitem__(self, i: int | slice) -> Trend | TrendsSlice:
        if isinstance(i, int):
            return self.trends[i]
        else:
            start = i.start if i.start is not None else 0
            stop  = i.stop  if i.stop  is not None else self.length
            step  = i.step  if i.step  is not None else 1

            start = start % self.length
            if stop != self.length: stop = stop % self.length

            return [self.trends[j] for j in range(start, stop, step)]

    def slice_itself(self, s: slice) -> Self:
        new = deepcopy(self)
        new.trends = deque(self[s])
        return new

    def __repr__(self):
        trends = []

        for x in self.trends:
            trends.append(
                f'{x.start_timestamp.strftime("%m-%d %H:%M")}: {x.change:7.1%}'
            )

        return (
                type(self).__name__ +
                '(\n    ' +
                (
                    '\n    '.join(trends)
                    if len(self.trends) <= 50
                    else f'total: {len(self.trends)}'
                ) +
                '\n)'
        )

    def initialize(self, ticks_or_trends):
        if not isinstance(ticks_or_trends, Trends):
            prices = [x.price for x in ticks_or_trends]
            timestamps = [x.timestamp for x in ticks_or_trends]
            changes = [
                (y - x) / x if x else 0 for x, y in zip(
                    prices[:-1],
                    prices[1:],
                )
            ]
            self.trends = deque(
                Trend(x, y, z) for x, y, z in zip(
                    changes,
                    timestamps[:-1],
                    timestamps[1:],
                )
            )
        else:
            self.trends = deepcopy(ticks_or_trends.trends)

        self.trends.reverse()

        i = 0
        while i + 2 < len(self.trends):
            t1, t2, t3 = self.trends[i], self.trends[i + 1], self.trends[i + 2]
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

        if len(self.trends) == 2:
            t1, t2 = self.trends[i], self.trends[i + 1]

            if t1.is_codirectional_with(t2) and self._are_within_limits(t1, t2):
                self._replace_by_concatenation(0, t1, t2)

        self.trends.reverse()

    @staticmethod
    def _concatenate(trends):
        return sum(trends[1:], start=trends[0])

    def _replace_by_concatenation(self, i, *trends):
        for x in trends:
            self.trends.remove(x)
        self.trends.insert(i, self._concatenate(trends))

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

    def generate_trends(self, ticks_or_trends: Iterable[Tick] | Trends) -> Trends:
        return Trends(ticks_or_trends, max_timeframe=self.value.max_timeframe, max_magnitude=self.value.max_magnitude)

    @staticmethod
    def generate_all(ticks_or_trends: Iterable[Tick] | Trends) -> list[Trends]:
        accumulator = []

        for trends_view in TrendsView:
            accumulator.append(
                trends_view.generate_trends(
                    ticks_or_trends if not accumulator else accumulator[-1]
                )
            )

        return accumulator


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
            return x / 5
        if pool and pool.liquidity and pool.liquidity < base:
            deviation = (base - pool.liquidity) / base
            return x * (1 + slope * deviation)
        return x

    def match(self, trend: Trend, pool: NetworkPool):
        return (
                self._have_same_sign(self.min_change, trend.change) and trend.get_magnitude() >= self._scale(self.get_magnitude(), pool) and
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

    def _extract_info(self, trends: TrendsSlice) -> tuple[Significance, Magnitude]:
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
            trends: Trends,
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
            max_timeframe=Timeframe(minutes=30)
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


@dataclass
class PlotSizeScheme:
    width: float = 16
    ratio: float = 0.25


@dataclass
class ColorScheme:
    upward: Color = '#00c979'
    downward: Color = '#ff706e'


@dataclass
class SizeScheme:
    price: float = 2
    volume: float = 0.5
    tick: float = 10
    pattern_mark: float = 100


@dataclass
class OpacityScheme:
    tick: float = 0.6
    volume: float = 0.3
    grid: float = 0.2


@dataclass
class MaxBinsScheme:
    x: int = None
    y: int = 6


class Backend(Enum):
    DEFAULT = ''
    AGG = 'Agg'


class Chart:
    def __init__(self, pool: NetworkPool):
        self.ticks: CircularList[Tick] = CircularList(capacity=config.getint('Chart', 'max_ticks'))
        self.pool: NetworkPool = pool
        self.previous_pattern_end_timestamp: Timestamp = None
        self.repetition_reset_cooldown = Timeframe(hours=config.getint('Patterns', 'repetition_reset_cooldown'))
        self.fig: Figure | None = None

    def __len__(self):
        return len(self.ticks)

    def __repr__(self):
        properties = [f'ticks: {len(self.ticks)}']

        if self.ticks:
            properties.append(f'timeframe: {self.ticks[0].timestamp.strftime("%m:%d %H:%M")} - {self.ticks[-1].timestamp.strftime("%m:%d %H:%M")}')
            properties.append(f'last tick: {repr(self.ticks[-1])}')
            complete_ticks = sum(map(lambda x: 1 if type(x) is CompleteTick else 0, self.ticks))
            properties.append(f'complete ticks: {complete_ticks / len(self.ticks):.0%}')

        return type(self).__name__ + '(' + ', '.join(properties)  + ')'

    def is_empty(self):
        return len(self.ticks) == 0

    def update(self, new_ticks: Tick | list[Tick]):

        if isinstance(new_ticks, Tick):

            if isinstance(new_ticks, IncompleteTick) and next(
                (True for (i, x) in enumerate(self.ticks) if isinstance(x, CompleteTick) and x.timestamp == new_ticks.timestamp),
                False
            ):
                return

            new_ticks = [new_ticks]

        if new_ticks:

            if (discard_index := next(
                (i for (i, x) in enumerate(self.ticks) if x.timestamp >= new_ticks[0].timestamp),
                None
            )) is not None:

                discarded_ticks = self.ticks[discard_index:]
                self.ticks.pop(len(discarded_ticks))

                if (save_index := next(
                    (i for (i, x) in enumerate(discarded_ticks) if x.timestamp > new_ticks[-1].timestamp),
                    None
                )) is not None:

                    new_ticks.extend(discarded_ticks[save_index:])

            self.ticks.extend(new_ticks)

    def get_pattern(self, only_new=False) -> PatternMatch | None:
        for match in Pattern.match_any(self.ticks, self.pool, reverse_trends_views_traversal=True):
            if (
                    only_new and
                    self.previous_pattern_end_timestamp and
                    (
                            match.start_timestamp < self.previous_pattern_end_timestamp and
                            (
                                    not self.repetition_reset_cooldown or
                                    self.previous_pattern_end_timestamp.time_elapsed() < self.repetition_reset_cooldown
                            )
                    )
            ):
                continue

            self.previous_pattern_end_timestamp = match.end_timestamp
            return match

    def _pad_ticks(self):
        ticks = []

        for x in self.ticks:

            if isinstance(x, IncompleteTick):
                x = CompleteTick(x.timestamp, x.price, volume=0)

            if ticks:

                last_tick = ticks[-1]
                time_difference = x.timestamp - last_tick.timestamp
                time_difference_in_units = time_difference // TIMESTAMP_UNIT

                # if there is any space to add new ticks between the current and the previous one, then do it
                if time_difference_in_units > 1:
                    for i in range(1, time_difference_in_units):

                        timestamp_and_price = last_tick.timestamp + TIMESTAMP_UNIT * i, last_tick.price
                        ticks.append(
                            CompleteTick(*timestamp_and_price, 0)
                            if isinstance(last_tick, CompleteTick) else
                            IncompleteTick(*timestamp_and_price)
                        )

            ticks.append(x)

        return ticks

    @staticmethod
    def _exponential_averaging(xs, alpha, n_avg=1):
        new_xs = [mean(xs[:n_avg])]
        for x in xs[1:]: new_xs.append(new_xs[-1] * (1 - alpha) + x * alpha)
        return new_xs

    @contextmanager
    def create_plot(
            self,
            trends_view: TrendsView = TrendsView.GLOBAL,
            mark_pattern_every_tick: int | None = None,

            plot_size_scheme: PlotSizeScheme = PlotSizeScheme(),
            max_timeframe: Timeframe = Timeframe(hours=config.getint('Plot', 'max_timeframe')),
            price_in_percents=False,
            datetime_format='%d %H:%M',
            backend=Backend.DEFAULT,

            color_scheme: ColorScheme = ColorScheme(),
            size_scheme: SizeScheme = SizeScheme(),
            opacity_scheme: OpacityScheme = OpacityScheme(),
            max_bins_scheme: MaxBinsScheme = MaxBinsScheme(),
    ) -> tuple[Pyplot, Figure, Axes, Axes]:

        default_backend = plt.get_backend()

        if backend is not Backend.DEFAULT:
            plt.switch_backend(backend.value)


        tick_limit = max_timeframe // TIMESTAMP_UNIT
        ticks = self._pad_ticks()[-tick_limit:]
        trends = trends_view.generate_trends(ticks)

        self.fig, ax1 = plt.subplots(figsize=(plot_size_scheme.width, plot_size_scheme.width * plot_size_scheme.ratio))
        ax2 = ax1.twinx()


        timestamps = [x.timestamp for x in ticks]
        prices = [x.price for x in ticks]

        if price_in_percents:
            average = mean(prices)
            prices = [x / average * 100 for x in prices]

        previous_color = None

        for x in trends:
            start = x.get_start_index(ticks)
            end =   x.get_end_index(  ticks) + 1
            color = color_scheme.upward if x.is_upward() else color_scheme.downward
            ax1.plot(
                timestamps[start:end],
                prices[start:end],
                color=color,
                linestyle='solid' if color != previous_color else 'dashed',
                linewidth=size_scheme.price,
                marker=None,
            )
            previous_color = color


        volume_ticks = []

        for x in ticks:
            if isinstance(x, IncompleteTick): break
            volume_ticks.append(x)

        if volume_ticks:
            ax2.plot(
                [x.timestamp for x in volume_ticks],
                self._exponential_averaging([x.volume for x in volume_ticks], 0.005, min(100, len(volume_ticks))),
                color='k',
                linewidth=size_scheme.volume,
                alpha=opacity_scheme.volume,
                marker=None,
            )


        if mark_pattern_every_tick:

            delta = (max(prices) - min(prices))
            # how large a vertical mark gap should be
            gap = delta * 0.05
            # how large range of ticks to sample max value (for mark vertical gap) from
            gap_x_diameter = 30
            # in timestamp units
            min_distance_between_marks = 30


            pattern_string_mapping = {}

            for pattern in Pattern:
                name = pattern.name

                if pattern is Pattern.DOWNTREND: pattern_string_mapping[pattern] = 'DW'
                if pattern is Pattern.SLOW_UPTREND: pattern_string_mapping[pattern] = 'SU'

                if pattern not in pattern_string_mapping.keys():
                    pattern_string_mapping[pattern] = next(
                        name[:i + 1] for i in range(len(name))
                        if name[:i + 1] not in pattern_string_mapping.values()
                    )


            indices = list(range(0, len(ticks), mark_pattern_every_tick))
            if indices[-1] != len(ticks) - 1: indices.append(len(ticks) - 1)

            patterns: list[int, Pattern] = []

            for i in indices:
                if patterns and i - patterns[-1][0] < min_distance_between_marks: continue
                match = next(Pattern.match_any(ticks[:i + 1], self.pool, reverse_trends_views_traversal=True), None)
                if match: patterns.append((i, match.pattern))
                    

            for pattern, string in pattern_string_mapping.items():

                if indices := [x[0] for x in patterns if x[1] is pattern]:

                    ax1.scatter(
                        [timestamps[i] for i in indices],
                        [
                            max(
                                prices[
                                    max(i - gap_x_diameter // 2, 0)
                                    :
                                    min(i + gap_x_diameter // 2 + 1, len(prices))
                                ]
                            )
                            + gap for i in indices
                        ],
                        marker=f'${string}$',
                        s=size_scheme.pattern_mark * len(string),
                        lw=0.7,
                        c='#000000',
                        zorder=ax1.get_zorder() + 2,
                    )


        ax1.margins(x=0, y=0)
        ax2.margins(x=0, y=0)

        xmin, xmax = ax1.get_xlim()
        xtimestamp = TIMESTAMP_UNIT / Timedelta(days=1)
        deviation = 2
        ax1.set_xlim(
            xmin=xmin - xtimestamp * deviation,
            xmax=xmax + xtimestamp * deviation,
        )

        ymin, ymax = ax1.get_ylim()
        delta = (ymax - ymin) / 100
        deviation = 5
        ax1.set_ylim(
            ymax=ymax + delta * deviation,
        )

        plt.box(False)
        ax1.spines['top'].set_visible(False); ax1.spines['right'].set_visible(False); ax1.spines['bottom'].set_visible(False); ax1.spines['left'].set_visible(False)
        ax2.spines['top'].set_visible(False); ax2.spines['right'].set_visible(False); ax2.spines['bottom'].set_visible(False); ax2.spines['left'].set_visible(False)

        ax1.tick_params(
            bottom=False,
            left=False, labelleft=False,
            labelright=True,
        )
        ax2.tick_params(
            labelbottom=False,
            left=False, labelleft=True,
            right=False, labelright=False,
        )

        ax1.tick_params(axis='both', labelsize=size_scheme.tick)
        ax2.tick_params(axis='y', labelsize=size_scheme.tick)

        ax1.xaxis.set_major_formatter(DateFormatter(datetime_format))
        if price_in_percents: ax1.yaxis.set_major_formatter(lambda x, _: f'{x:.0f}%')
        ax2.yaxis.set_major_formatter(lambda x, _: f'${x:.0f}')

        ax1.tick_params(colors=(0, 0, 0, opacity_scheme.tick))
        ax2.tick_params(colors=(0, 0, 0, opacity_scheme.tick))

        if max_bins_scheme.x: ax1.xaxis.set_major_locator(MaxNLocator(nbins=max_bins_scheme.x))
        if max_bins_scheme.y: ax1.yaxis.set_major_locator(MaxNLocator(nbins=max_bins_scheme.y))
        if max_bins_scheme.y: ax2.yaxis.set_major_locator(MaxNLocator(nbins=max_bins_scheme.y))

        ax1.grid(
            color='k',
            alpha=opacity_scheme.grid,
            linewidth=0.5,
        )


        yield plt, self.fig, ax1, ax2

        if backend is not Backend.DEFAULT:
            plt.switch_backend(default_backend)

        if self.fig:
            plt.close(self.fig)

        plt.cla()
        plt.clf()
        plt.close('all')
        gc.collect()


@dataclass
class Pool(NetworkPool):
    chart: Chart = None

    def __post_init__(self):
        self.chart = Chart(pool=self)

    def __eq__(self, other):
        return isinstance(other, NetworkPool) and super().__eq__(other)

    def __hash__(self):
        return super().__hash__()
