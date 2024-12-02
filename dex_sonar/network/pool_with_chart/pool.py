from dataclasses import dataclass
from typing import Self

from .chart import Chart
from ..network import Pool as BasePool


@dataclass
class Pool(BasePool):
    chart: Chart = None

    def __post_init__(self):
        self.chart = Chart(pool=self)

    def __eq__(self, other):
        return isinstance(other, BasePool) and super().__eq__(other)

    def __hash__(self):
        return super().__hash__()

    def update(self, other: Self):
        super().update(other)
        self.chart.update(other.chart.get_ticks())
