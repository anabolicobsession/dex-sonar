from enum import Enum
from typing import Self
from dataclasses import dataclass


Id = str
Address = str


class UnknownNetwork(Exception):
    ...


@dataclass(frozen=True)
class _NetworkValue:
    id: Id
    native_token_address: Address


class Network(Enum):
    TON = _NetworkValue('ton', 'EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c')

    def __repr__(self):
        return f'{type(self).__name__}({self.name})'

    def get_id(self) -> Id:
        return self.value.id

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
class Pool:
    network: Network
    address: Address
    base_token: Token
    quote_token: Token

    def __eq__(self, other):
        return isinstance(other, Pool) and self.network == other.network and self.address == other.address

    def __hash__(self):
        return hash((self.network, self.address))

    def __repr__(self):
        return f'{type(self).__name__}({repr(self.base_token)}/{repr(self.quote_token)})'

    def update(self, other: Self):
        self.base_token.update(other.base_token)
        self.quote_token.update(other.quote_token)
