from dataclasses import dataclass
from enum import Enum
from typing import Self

from dex_sonar.utils.time import Timestamp


Id = str
Address = str


class UnknownNetwork(Exception):
    ...


@dataclass
class _NetworkValue:
    id: Id
    name: str
    native_token_address: Address


class Network(Enum):
    TON = _NetworkValue('ton', 'TON', 'EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c')

    def __repr__(self):
        return f'{type(self).__name__}({self.value.name})'

    def get_id(self) -> Id:
        return self.value.id

    def get_name(self):
        return self.value.name

    def get_native_token_address(self) -> Address:
        return self.value.native_token_address

    @classmethod
    def from_id(cls, id: Id) -> Self | None:
        for network in cls:
            if network.value.id == id:
                return network
        raise UnknownNetwork(id)


@dataclass
class Token:
    network: Network
    address: Address
    ticker: str = None
    name: str = None

    def __eq__(self, other):
        return isinstance(other, Token) and self.network == other.network and self.address == other.address

    def __hash__(self):
        return hash((self.network, self.address))

    def __repr__(self):
        return f'{type(self).__name__}({self.ticker})'

    def update(self, other: Self):
        self.ticker = other.ticker
        self.name = other.name

    def is_native_currency(self):
        return self.address == self.network.get_native_token_address()


@dataclass
class DEX:
    id: Id
    name: str = None

    def __eq__(self, other):
        return isinstance(other, DEX) and self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return f'{type(self).__name__}({self.id})'

    def update(self, other: Self):
        self.name = other.name


@dataclass
class TimePeriodsData:
    m5:  float = None
    h1:  float = None
    h6:  float = None
    h24: float = None


@dataclass
class Pool:
    network: Network
    address: Address
    base_token: Token
    quote_token: Token
    dex: DEX

    price_native: float
    price_usd: float
    fdv: float
    volume: float
    liquidity: float

    price_change: TimePeriodsData
    creation_date: Timestamp

    def __eq__(self, other):
        return isinstance(other, Pool) and self.address == other.address

    def __hash__(self):
        return hash(self.address)

    def __repr__(self):
        return f'{type(self).__name__}({repr(self.base_token)}/{repr(self.quote_token)})'

    def update(self, other: Self):
        self.base_token.update(other.base_token)
        self.quote_token.update(other.quote_token)
        self.dex.update(other.dex)

        self.price_native = other.price_native
        self.price_usd = other.price_usd
        self.fdv = other.fdv
        self.volume = other.volume
        self.liquidity = other.liquidity

        self.price_change = other.price_change
        self.creation_date = other.creation_date

    def has_native_quote_token(self):
        return self.quote_token.is_native_currency()

    def get_name(self):
        return self.base_token.ticker + '/' + self.quote_token.ticker

    def get_shortened_name(self):
        return self.base_token.ticker
