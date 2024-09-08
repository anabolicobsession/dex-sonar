from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timezone
from enum import Enum
from statistics import mean
from typing import Any, Generic, Iterable, TypeVar

from matplotlib import pyplot as plt
from matplotlib.axes import Axes
from matplotlib.dates import DateFormatter
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from dex_sonar.auxiliary.time import Timedelta, Timestamp
from dex_sonar.config.config import config
from .patterns import PatternOld, PatternMatch
from .segments import SegmentsViews
from .ticks import CompleteTick, IncompleteTick, Tick
from ..network import Pool as NetworkPool


Pyplot = Any
Color = str
TIMESTAMP_UNIT = Timedelta(minutes=1)


plt.rcParams.update({'mathtext.default': 'regular'})


class NotEnoughItemsToPop(Exception):
    ...


T = TypeVar('T')


class CircularList(Generic[T]):
    def __init__(self, capacity):
        self.list: list[T] = [None] * capacity
        self.capacity = capacity
        self.beginning = 0
        self.size = 0

    def __len__(self):
        return self.size

    def __iter__(self):
        return (self.list[(self.beginning + i) % self.capacity] for i in range(self.size))

    def __repr__(self):
        return '[' + ', '.join([repr(item) for item in self]) + ']'

    def append(self, item: T):
        self.list[self._translate_index(self.size)] = item

        if self.size < self.capacity:
            self.size += 1
        else:
            self.beginning = self._translate_index(1)

    def extend(self, iterable: Iterable[T]):
        for item in iterable:
            self.append(item)

    def pop(self, n=1):
        if self.size - n >= 0:
            self.size -= n
        else:
            if not self.size:
                raise NotEnoughItemsToPop('No items to pop')
            else:
                raise NotEnoughItemsToPop(f'There are only {self.size} items to pop ({n} were tried to be popped')

    def clear(self):
        self.size = 0

    def _translate_index(self, i):
        base = self.beginning if i >= 0 else self.beginning + self.size
        return (base + i) % self.capacity

    def __getitem__(self, i: int | slice):

        if isinstance(i, int):
            if not -self.size <= i < self.size:
                raise IndexError(f'Index {i} is out of range [{-self.size}, {self.size})')
            return self.list[self._translate_index(i)]

        else:
            start = i.start if i.start is not None else 0
            stop =  i.stop  if i.stop  is not None else self.size
            step =  i.step  if i.step  is not None else 1

            start = start % self.size
            if stop != self.size: stop = stop % self.size

            # if not (-self.size <= start <= stop <= 0 or 0 <= start <= stop <= self.size):
            #     raise IndexError(f'Slice {i} doesn\'t satisfy condition {-self.size} <= start <= stop <= 0 or 0 <= start <= stop <= {self.size}')

            return [self.list[self._translate_index(j)] for j in range(start, stop, step)]


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
        self.repetition_reset_cooldown = Timedelta(hours=config.getint('Patterns', 'repetition_reset_cooldown'))
        self.fig: Figure | None = None

    def __len__(self):
        return len(self.ticks)

    def __repr__(self):
        properties = [f'ticks: {len(self.ticks):4}']

        if self.ticks:
            properties.append(f'timeframe: {self.ticks[0].timestamp.strftime("%m.%d %H:%M")} - {self.ticks[-1].timestamp.strftime("%m:%d %H:%M")}')
            complete_ticks = len([x for x in self.ticks if isinstance(x, CompleteTick)])
            percent = f'{complete_ticks / len(self.ticks):.0%}'
            properties.append(f'complete ticks: {percent:3}')
            properties.append(f'last tick: {repr(self.ticks[-1])}')

        return type(self).__name__ + '(' + ', '.join(properties)  + ')'

    def is_empty(self):
        return len(self.ticks) == 0

    def get_ticks(self):
        return self.ticks

    def get_timeframe(self) -> Timedelta:
        return self.ticks[-1].timestamp.positive_difference(self.ticks[0].timestamp)

    def update(self, new_ticks: Tick | list[Tick]):

        if isinstance(new_ticks, Tick):
            new_ticks = [new_ticks]

        if isinstance(new_ticks[0], IncompleteTick) and next(
            (True for (i, x) in enumerate(self.ticks) if isinstance(x, CompleteTick) and x.timestamp == new_ticks[0].timestamp),
            False
        ):
            return

        if isinstance(new_ticks[0], IncompleteTick) and self.ticks and self.ticks[-1].price == new_ticks[0].price:
            return

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
        for match in PatternOld.match_any(self.ticks, self.pool, reverse_trends_views_traversal=True):
            if (
                    only_new and
                    self.previous_pattern_end_timestamp and
                    (
                            self.previous_pattern_end_timestamp > match.start_timestamp
                            and
                            (
                                    not self.repetition_reset_cooldown or
                                    match.start_timestamp.positive_difference(self.previous_pattern_end_timestamp) < self.repetition_reset_cooldown
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

    def can_be_plotted(self):
        return self.get_timeframe() >= Timedelta.from_other(config.get_timedelta_from_minutes('Message', 'chart_min_timeframe'))

    @contextmanager
    def create_plot(
            self,
            trends_view: SegmentsViews = SegmentsViews.DEFAULT,
            mark_pattern_every_tick: int | None = None,

            plot_size_scheme: PlotSizeScheme = PlotSizeScheme(),
            max_timeframe: Timedelta = Timedelta(hours=config.getint('Plot', 'max_timeframe')),
            price_in_percents=False,
            datetime_format='%d %H:%M',
            specific_timezone: timezone = None,
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
        trends = trends_view.generate(ticks)

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

            for pattern in PatternOld:
                name = pattern.name

                if pattern is PatternOld.DOWNTREND: pattern_string_mapping[pattern] = 'DW'
                if pattern is PatternOld.SLOW_UPTREND: pattern_string_mapping[pattern] = 'SU'

                if pattern not in pattern_string_mapping.keys():
                    pattern_string_mapping[pattern] = next(
                        name[:i + 1] for i in range(len(name))
                        if name[:i + 1] not in pattern_string_mapping.values()
                    )


            indices = list(range(0, len(ticks), mark_pattern_every_tick))
            if indices[-1] != len(ticks) - 1: indices.append(len(ticks) - 1)

            patterns: list[int, PatternOld] = []

            for i in indices:
                if patterns and i - patterns[-1][0] < min_distance_between_marks: continue
                match = next(PatternOld.match_any(ticks[:i + 1], self.pool, reverse_trends_views_traversal=True), None)
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

        ax1.xaxis.set_major_formatter(DateFormatter(datetime_format, tz=specific_timezone))
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
