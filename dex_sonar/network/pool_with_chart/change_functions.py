from abc import ABC, abstractmethod
from dataclasses import dataclass

from .segments import Change, Timeframe
from ..network import Pool


Changes = (Change | None, Change | None)


class ChangeFunction(ABC):
    @abstractmethod
    def __call__(self, timeframe: Timeframe, pool: Pool) -> Changes:
        ...


@dataclass
class Numbers(ChangeFunction):
    min_change: Change = None
    min_change_second_order: Change = None

    def __post_init__(self):
        if not self.min_change and not self.min_change_second_order:
            raise ValueError('Both minimal changes can\'t be set to None. Choose only one')

    def __call__(self, _, __) -> Changes:
        return self.min_change, self.min_change_second_order


class ScalingFunction(ABC):
    @abstractmethod
    def __call__(self, min_change: Change, min_change_second_order: Change, timeframe: Timeframe, pool: Pool) -> Changes:
        ...


class LinearScalingByLiquidity:
    ...


# transforming function ? first value function?
class Composer:
    def __init__(self, change_function, scaling_functon):
        ...
