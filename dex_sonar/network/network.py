from dataclasses import dataclass
from enum import Enum
from typing import Self

from dex_sonar.auxiliary.time import Timestamp


Id = str
Address = str


class UnknownNetwork(Exception):
    ...


@dataclass
class _NetworkValue:
    id: Id
    name: str
    native_token_address: Address
    native_token_ticker: str


class Network(Enum):
    TON = _NetworkValue(
        id='ton',
        name='TON',
        native_token_address='EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c',
        native_token_ticker='TON'
    )

    @classmethod
    def from_id(cls, id: Id) -> Self | None:
        for network in cls:
            if network.value.id == id:
                return network
        raise UnknownNetwork(id)

    @property
    def id(self) -> Id:
        return self.value.id

    @property
    def name(self) -> str:
        return self.value.name

    @property
    def native_token_address(self) -> Address:
        return self.value.native_token_address

    @property
    def native_token_ticker(self) -> Address:
        return self.value.native_token_ticker

    def __eq__(self, other):
        return isinstance(other, Network) and self.value.id == other.value.id

    def __hash__(self):
        return hash(self.value.id)

    def __repr__(self):
        return f'{type(self).__name__}({self.value.name})'


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
        return self.address == self.network.native_token_address


@dataclass
class DEX:
    network: Network
    id: Id
    name: str

    def __eq__(self, other):
        return isinstance(other, DEX) and self.network == other.network and self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return f'{type(self).__name__}({self.id})'

    def update(self, other: Self):
        self.name = other.name

    @classmethod
    def from_id(cls, network: Network, id: Id) -> Self:
        return cls(
            network,
            id,
            {
                'stonfi': 'STON.fi',
                'dedust': 'DeDust',
            }[id],
        )


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

    price_quote: float
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

        self.price_quote = other.price_quote
        self.price_usd = other.price_usd
        self.fdv = other.fdv
        self.volume = other.volume
        self.liquidity = other.liquidity

        self.price_change = other.price_change
        self.creation_date = other.creation_date

    @property
    def base_ticker(self):
        return self.base_token.ticker

    @property
    def quote_ticker(self):
        return self.quote_token.ticker

    @property
    def dex_name(self):
        return self.dex.name

    def has_native_quote_token(self):
        return self.quote_token.is_native_currency()

    def form_name(
            self,
            shortened=False,
            shortened_if_native=False,
            dex=False,
    ):
        name = self.base_token.ticker

        if not (shortened or shortened_if_native and self.quote_token.is_native_currency()):
            name += f' / {self.quote_ticker}'

        if dex:
            name += f' ({self.dex.id})'

        return name
