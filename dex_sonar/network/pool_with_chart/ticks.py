from abc import ABC
from dataclasses import dataclass

from dex_sonar.auxiliary.time import Timestamp


Price = float


@dataclass
class _AbstractDataclass(ABC):
    def __new__(cls, *args, **kwargs):
        if cls == _AbstractDataclass or cls.__bases__[0] == _AbstractDataclass:
            raise TypeError('Can\'t instantiate an abstract class')
        return super().__new__(cls)


@dataclass
class Tick(_AbstractDataclass):
    timestamp: Timestamp
    price: Price

    def __repr__(self):
        return f'{type(self).__name__}({self.timestamp.strftime("%m-%d %H:%M:%S")}, {self.price})'


@dataclass(repr=False)
class CompleteTick(Tick):
    volume: float


@dataclass(repr=False)
class IncompleteTick(Tick):
    ...
