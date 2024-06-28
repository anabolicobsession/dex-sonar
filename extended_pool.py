import logging
from abc import ABC
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from itertools import chain
from statistics import mean
from typing import Self, Iterable, Collection, Sequence

from matplotlib import pyplot as plt
from matplotlib.dates import DateFormatter
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

import settings
from network import Pool as NetworkPool, DEX


TICK_MERGE_MAXIMUM_CHANGE = 0.1
LAST_TREND_DURATION = timedelta(minutes=3)

DURATION_TO_MERGE = timedelta(minutes=3)
_TIMEFRAME = timedelta(seconds=60)
Index = int
CHART_MAX_TICKS = 2000


logger = logging.getLogger(__name__)


class TimeGapBetweenCharts(Exception):
    ...


class OutdatedData(Exception):
    ...


@dataclass(frozen=True)
class _AbstractDataclass(ABC):
    def __new__(cls, *args, **kwargs):
        if cls == _AbstractDataclass or cls.__bases__[0] == _AbstractDataclass:
            raise TypeError('Can\'t instantiate an abstract class')
        return super().__new__(cls)


@dataclass(frozen=True)
class BaseTick(_AbstractDataclass):
    timestamp: datetime
    price: float

    def __repr__(self):
        return f'{self.__name__}({self.timestamp}, {self.price})'


@dataclass(frozen=True)
class CompleteTick(BaseTick):
    volume: float


@dataclass(frozen=True)
class IncompleteTick(BaseTick):
    ...


class CircularList(list):
    def __init__(self, capacity):
        super().__init__([None] * capacity)
        self.beginning = 0
        self.size = 0
        self.capacity = capacity

    def _get_index(self, shift):
        base = self.beginning if shift >= 0 else self.beginning + self.size
        return (base + shift) % self.capacity

    def _is_integral(self):
        return self.beginning + self.size <= self.capacity

    def __len__(self):
        return self.size

    def __getitem__(self, index: Index | slice):
        if isinstance(index, int):
            if not -self.size <= index < self.size:
                raise IndexError(f'Index {index} out of range [{-self.size}, {self.size})')
            return super().__getitem__(self._get_index(index))
        else:
            start = index.start if index.start is not None else 0
            stop = index.stop if index.stop is not None else self.size

            if start > stop or start < 0 or stop > self.size:
                raise IndexError(f'Slice out of range: {start}:{stop}')

            start = self._get_index(start)
            stop = self._get_index(stop)

            if self._is_integral() or stop > start or index.start == index.stop:
                return super().__getitem__(slice(start, stop))
            else:
                return list(chain(
                    super().__getitem__(slice(start, self.capacity)),
                    super().__getitem__(slice(stop)),
                ))

    def __iter__(self):
        for index in range(self.size):
            yield super().__getitem__(self._get_index(index))

    def __repr__(self):
        return '[' + ', '.join([repr(item) for item in self]) + ']'

    def get_internal_repr(self):
        super_class = super()
        internal = [repr(super_class.__getitem__(i)) for i in range(self.capacity)]
        return '[' + ', '.join(internal) + ']'

    def append(self, item):
        index = self._get_index(self.size)

        if self.size < self.capacity:
            self.size += 1
        else:
            self.beginning = self._get_index(1)

        self[index] = item

    def extend(self, iterable: Iterable):
        for item in iterable:
            self.append(item)

    def set(self, index: Index, iterable: Collection):
        if not 0 <= index <= self.size:
            raise IndexError(f'Index out of range: {index}')

        # if index + len(iterable) >= self.size:
        self.size = index
        self.extend(iterable)
        # else:
        #     raise IndexError(
        #         'Too few items to set or too small index. '
        #         'New items must override existing items for a small enough index, otherwise behaviour is undefined'
        #     )

    def pop(self, index=None):
        if self.size:
            self[self._get_index(self.size - 1)] = None
            self.size -= 1
        else:
            raise IndexError('No items to pop')

    def pop_all(self):
        while self.size:
            self.pop()


@dataclass(frozen=True)
class Trend:
    change: float
    beginning: Index
    end: Index

    def __add__(self, other) -> Self:
        return Trend(self.change + other.change, self.beginning, other.end)

    @staticmethod
    def have_same_trend(a, b):
        return a.change * b.change >= 0

    @staticmethod
    def can_be_merged(a, b, c, ticks):
        # a1, a2 = ticks[a.beginning].timestamp, ticks[a.end].timestamp
        # b1, b2 = ticks[b.beginning].timestamp, ticks[b.end].timestamp
        # c1, c2 = ticks[c.beginning].timestamp, ticks[c.end].timestamp

        if Trend.have_same_trend(a, c) and not Trend.have_same_trend(a, b):

            # if b1 - b2 <= DURATION_TO_MERGE and b1 - b2 <= min(a1 - a2, c1 - c2):
            #     return True

            if abs(b.change) <= min(abs(a.change), abs(c.change)) and abs(b.change) <= TICK_MERGE_MAXIMUM_CHANGE:
                return True

        return False


@dataclass(frozen=True)
class Pattern:
    min_change: float
    min_duration: timedelta = None
    max_duration: timedelta = None

    def match(self, trend: Trend, ticks: Sequence[BaseTick], p):

        base = 150_000
        scale_factor = 1 if p.liquidity >= base else 1 + 3 * (base - p.liquidity) / base
        min_change = self.min_change * scale_factor

        if trend.change >= min_change >= 0 or 0 >= min_change >= trend.change:

            duration = abs(ticks[trend.end].timestamp - ticks[trend.beginning].timestamp)

            if self.min_duration and duration < self.min_duration:
                return False

            if self.max_duration and duration > self.max_duration:
                return False

            return True

        return False


_FACTOR = 1 if settings.PRODUCTION_MODE else 0


def _fraction(percent):
    return percent / 100 * _FACTOR


class Signal(Enum):

    SHARP_DUMP = [
        Pattern(_fraction(-20),  max_duration=timedelta(minutes=60)),
    ]

    DUMP = [
        Pattern(_fraction(-15),  max_duration=timedelta(minutes=150)),
    ]

    UPTREND = [
        Pattern(_fraction(15), min_duration=timedelta(minutes=150)),
    ]

    REVERSAL = [
        Pattern(_fraction(-20), min_duration=timedelta(minutes=60)),
        Pattern(_fraction(5), min_duration=timedelta(minutes=20)),
    ]

    def __len__(self):
        return len(self.value)

    def __repr__(self):
        return ' '.join([x.title() for x in self.name.split('_')])

    def get_pattern(self):
        return self.value


Magnitude = float


class Chart:
    def __init__(self):
        self.ticks: CircularList[BaseTick] = CircularList(capacity=CHART_MAX_TICKS)
        self.signal_end_timestamp: datetime | None = None
        self.figure: Figure | None = None

    def __repr__(self):
        return f'{type(self).__name__}({[repr(t) for t in self.ticks]})'

    def update(self, ticks: BaseTick | Collection[BaseTick]):
        ticks = deepcopy(ticks)

        if isinstance(ticks, BaseTick):
            ticks = [ticks]

        if ticks:
            for i in range(len(self.ticks)):
                if self.ticks[i].timestamp >= ticks[0].timestamp:
                    i_ticks = self.ticks[i:]

                    if i_ticks[-1].timestamp > ticks[-1].timestamp:
                        first_index = next(j for j, x in enumerate(i_ticks) if x.timestamp > ticks[-1].timestamp)
                        ticks.extend(i_ticks[first_index:])

                    self.ticks.set(
                        i,
                        ticks,
                    )

                    return

            # if len(self.ticks) == 0 and not isinstance(ticks[0], CompleteTick):
            #     return

            if self.ticks and self.ticks[-1].timestamp > ticks[0].timestamp:
                raise IndexError('Charts can\'t be concatenated')

            self.ticks.extend(ticks)

    @staticmethod
    def _construct_segments(ticks):
        prices = [c.price for c in ticks]
        previous_prices = [0, *prices[:-1]]

        changes = [
            (current - previous) / previous if previous else 0 for current, previous in zip(
                prices,
                previous_prices,
            )
        ]

        trends = deque(Trend(c, beginning=i - 1 if i else 0, end=i) for i, c in enumerate(changes))

        i = 0
        while i + 2 < len(trends):
            t1, t2, t3 = trends[i], trends[i + 1], trends[i + 2]

            if Trend.have_same_trend(t1, t2):
                trends.remove(t1)
                trends.remove(t2)
                trends.insert(i, t1 + t2)
                i = max(i - 2, 0)
                continue

            if Trend.have_same_trend(t2, t3):
                trends.remove(t2)
                trends.remove(t3)
                trends.insert(i + 1, t2 + t3)
                i = max(i - 2, 0)
                continue

            if Trend.can_be_merged(t1, t2, t3, ticks):
                trends.remove(t1)
                trends.remove(t2)
                trends.remove(t3)
                trends.insert(i, t1 + t2 + t3)
                i = max(i - 2, 0)
                continue

            i += 1

        return trends

    def get_signal(self, pool, only_new=False) -> tuple[Signal, Magnitude] | None:
        trends = self._construct_segments(self.ticks)

        if len(trends) < 3:
            return None

        if len(trends) < max(map(len, Signal)):
            return None

        for signal in Signal:
            trends_to_check = [[trends[i] for i in range(-len(signal), 0)]]

            timestamp1 = self.ticks[trends[-1].beginning].timestamp
            timestamp2 = self.ticks[trends[-1].end].timestamp

            if abs(timestamp1 - timestamp2) <= LAST_TREND_DURATION:
                trends_to_check.append([trends[i] for i in range(-len(signal) - 1, -1)])

            for i, last_trends in enumerate(trends_to_check):

                if all([
                    p.match(t, self.ticks, pool)
                    for p, t in zip(signal.get_pattern(), last_trends)
                ]):
                    if only_new:
                        first_timestamp = self.ticks[last_trends[0].beginning].timestamp

                        if self.signal_end_timestamp and first_timestamp < self.signal_end_timestamp:
                            return None

                        self.signal_end_timestamp = self.ticks[last_trends[-1].end].timestamp

                    magnitude = max([abs(x.change) for x in last_trends])
                    return signal, magnitude

        return None

    def _get_padded_ticks(self):
        ticks = [self.ticks[0]]

        for x in self.ticks[1:]:
            if isinstance(x, IncompleteTick):
                x = CompleteTick(x.timestamp, x.price, 0)

            if x.timestamp > ticks[-1].timestamp + _TIMEFRAME:
                last_tick = ticks[-1]
                diff = int((x.timestamp.timestamp() - last_tick.timestamp.timestamp()) / _TIMEFRAME.total_seconds())

                for i in range(1, diff):
                    ticks.append(
                        CompleteTick(
                            last_tick.timestamp + _TIMEFRAME * i,
                            last_tick.price,
                            0,
                        )
                        if isinstance(last_tick, CompleteTick) else
                        IncompleteTick(
                            last_tick.timestamp + _TIMEFRAME * i,
                            last_tick.price,
                        )
                    )

            ticks.append(x)

        return ticks

    @staticmethod
    def _exponential_averaging(xs, alpha, n_avg=1):
        new_xs = [mean(xs[:n_avg])]

        for x in xs[1:]:
            new_xs.append(new_xs[-1] * (1 - alpha) + x * alpha)

        return new_xs

    def _get_mapped_index(self, index, ticks):
        timestamp = self.ticks[index].timestamp
        return next(i for i, x in enumerate(ticks) if x.timestamp == timestamp)

    def create_plot(
            self,
            width=16,
            ratio=0.25,

            percent=False,
            tick_limit=2000,
            datetime_format='%d %H:%M',

            volume_width=0.5,
            volume_opacity=0.3,
            grid_opacity=0.2,

            tick_size=10,
            tick_opacity=0.6,
            xtick_bins=None,
            ytick_bins=6,
    ) -> Figure:

        if self.figure:
            plt.close(self.figure)
            plt.clf()
            self.figure = None

        ticks = self._get_padded_ticks()
        if tick_limit:
            ticks = ticks[-tick_limit:]
        trends = self._construct_segments(ticks)

        fig, ax = plt.subplots(figsize=(width, width * ratio))
        ax2 = ax.twinx()

        for x in trends:
            trend_ticks = ticks[x.beginning:x.end + 1]

            ax.plot(
                [y.timestamp for y in trend_ticks],
                [y.price if not percent else y.price / ticks[0].price * 100 for y in trend_ticks],
                color='#00c979' if x.change > 0 else '#ff6969',
                linewidth=2,
                marker=None,
            )

        volume_ticks = []
        for x in ticks:
            if isinstance(x, IncompleteTick):
                break
            volume_ticks.append(x)

        if volume_ticks:
            ax2.plot(
                [x.timestamp for x in volume_ticks],
                self._exponential_averaging([x.volume for x in volume_ticks], 0.005, 100),
                color='k',
                linewidth=volume_width,
                alpha=volume_opacity,
                marker=None,
            )

        plt.margins(x=0, y=0)

        plt.box(False)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_visible(False)
        ax.spines['left'].set_visible(False)

        ax.tick_params(axis='both', labelsize=tick_size)
        ax2.tick_params(axis='y', labelsize=tick_size)

        ax.xaxis.set_major_formatter(DateFormatter(datetime_format))
        if percent:
            ax.yaxis.set_major_formatter(lambda x, _: f'{x:.0f}%')
        ax2.yaxis.set_major_formatter(lambda x, _: f'${x:.0f}')

        ax.tick_params(
            bottom=False,
            left=False,
            labelleft=False,
            labelright=True,
        )
        ax2.tick_params(
            left=False,
            labelleft=True,
            right=False,
            labelright=False,
        )

        ax.grid(
            color='k',
            alpha=grid_opacity,
            linewidth=0.5,
        )

        if xtick_bins: ax.xaxis.set_major_locator(MaxNLocator(nbins=xtick_bins))
        if ytick_bins: ax.yaxis.set_major_locator(MaxNLocator(nbins=ytick_bins))
        if ytick_bins: ax2.yaxis.set_major_locator(MaxNLocator(nbins=ytick_bins))

        ax.tick_params(colors=(0, 0, 0, tick_opacity))
        ax2.tick_params(colors=(0, 0, 0, tick_opacity))

        ax.set_zorder(ax2.get_zorder() + 1)
        ax.patch.set_visible(False)

        self.figure = fig
        return fig

    def clear_plot(self):
        if self.figure:
            plt.close(self.figure)

@dataclass
class TimePeriodsData:
    m5:  float = None
    h1:  float = None
    h6:  float = None
    h24: float = None


@dataclass
class Pool(NetworkPool):
    price_usd: float
    price_native: float
    volume: float

    price_change: TimePeriodsData
    dex: DEX

    liquidity: float = None
    fdv: float = None
    creation_date: datetime = None

    chart: Chart = None

    def __post_init__(self):
        self.chart = Chart()

    def update(self, other: Self):
        super().update(other)

        self.price_usd = other.price_usd
        self.price_native = other.price_native
        self.liquidity = other.liquidity
        self.volume = other.volume
        self.fdv = other.fdv

        self.price_change = other.price_change
        self.dex.update(other.dex)
        self.creation_date = other.creation_date

    def __eq__(self, other):
        return super().__eq__(other)

    def __hash__(self):
        return super().__hash__()
