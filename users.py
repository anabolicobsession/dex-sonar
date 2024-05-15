import os
import time
from enum import Enum
from typing import Any

import pandas as pd

import settings
from network import Token


Id = int
Timestamp = float


class TokenBalance:
    def __init__(self, token, amount=None, rate=None):
        self.token: Token = token
        self.amount = amount
        self.rate = rate

    def set(self, amount=None, rate=None):
        if amount: self.amount = amount
        if rate: self.rate = rate

    def calculate_balance(self):
        return self.amount * 10 ** -self.token.decimals * self.rate


class User:
    def __init__(self, id: Id):
        self.id: Id = id
        self.token_balances: dict[Token, TokenBalance] = {}

    def add_token_balance(self, token_balance: TokenBalance):
        self.token_balances[token_balance.token] = token_balance

    def get_token_balance(self, token: Token) -> TokenBalance | None:
        return self.token_balances.get(token, None)

    def remove_token_balance(self, token_or_token_balance: Token | TokenBalance):
        self.token_balances.pop(token_or_token_balance if isinstance(token_or_token_balance, Token) else token_or_token_balance.token)


class Property(str, Enum):
    ID = 'id'
    MAIN_MESSAGE_ID = 'main_message_id'
    WALLET = 'wallet'


property_dtypes = {
    Property.ID: 'int',
    Property.MAIN_MESSAGE_ID: 'float',
    Property.WALLET: 'str',
}


properties_without_id = [Property.MAIN_MESSAGE_ID, Property.WALLET]

class _MutelistProperty(str, Enum):
    ID = Property.ID
    TOKEN = 'token'
    MUTE_UNTIL = 'mute_until'


_mutelist_property_dtypes = {
    _MutelistProperty.ID: property_dtypes[Property.ID],
    _MutelistProperty.TOKEN: 'str',
    _MutelistProperty.MUTE_UNTIL: 'float',
}


class Users:
    def __init__(self):
        self.users: dict[Id, User] = {}
        self.user_database = pd.DataFrame(
            index=pd.Series(name=Property.ID, dtype=property_dtypes[Property.ID]),
            data={k: pd.Series(dtype=v) for k, v in property_dtypes.items() if k is not Property.ID}
        )
        self.mutelists = pd.DataFrame(
            data={k: pd.Series(dtype=v) for k, v in _mutelist_property_dtypes.items()}
        )

        if os.path.isfile(settings.DATABASES_PATH_USERS):
            self.user_database = pd.read_csv(settings.DATABASES_PATH_USERS, index_col=0, dtype=property_dtypes)

            for id in self.user_database.index:
                self.users[id] = User(id)

        if os.path.isfile(settings.DATABASES_PATH_MUTELISTS):
            self.mutelists = pd.read_csv(settings.DATABASES_PATH_MUTELISTS, dtype=_mutelist_property_dtypes)

    def has_user(self, id: Id):
        return id in self.users

    def get_user(self, id: Id) -> User:
        return self.users[id]

    def get_users(self) -> list[User]:
        return list(self.users.values())

    def _save_user_database_to_disk(self):
        self.user_database.to_csv(settings.DATABASES_PATH_USERS)

    def add_user(self, id: Id):
        self.users[id] = User(id)
        self.user_database.loc[id] = None, ''
        self._save_user_database_to_disk()

    def remove_user(self, id: Id):
        self.users.pop(id)
        self.user_database.drop(index=id, inplace=True)
        self._save_user_database_to_disk()

    def set_property(self, user: User, property: Property, value):
        self.user_database.loc[user.id, property] = value
        self._save_user_database_to_disk()

    def clear_property(self, user: User, property: Property):
        match property:
            case Property.MAIN_MESSAGE_ID:
                self.user_database.loc[user.id, property] = pd.NA
            case Property.WALLET:
                self.user_database.loc[user.id, property] = ''

        self._save_user_database_to_disk()

    def get_property(self, user: User, property: Property) -> Any | None:
        cell = self.user_database.loc[user.id, property]

        match property:
            case Property.MAIN_MESSAGE_ID:
                if pd.isna(cell):
                    return None
                else:
                    return int(cell)
            case Property.WALLET:
                if pd.isna(cell):
                    return None

        return cell

    def _save_mutelists_to_disk(self):
        self.mutelists.to_csv(settings.DATABASES_PATH_MUTELISTS, index=False)

    def _find_mutelists_indices(self, user: User, token: Token):
        return self.mutelists[(self.mutelists[_MutelistProperty.ID] == user.id) & (self.mutelists[_MutelistProperty.TOKEN] == token.address)].index

    def is_muted(self, user: User, token: Token):
        indices = self._find_mutelists_indices(user, token)
        return False if len(indices) == 0 else time.time() < self.mutelists.loc[indices.item()][_MutelistProperty.MUTE_UNTIL]

    def _set_mute_until(self, user: User, token: Token, mute_until: Timestamp | None):
        indices = self._find_mutelists_indices(user, token)
        self.mutelists.loc[len(self.mutelists.index) if len(indices) == 0 else indices.item()] = user.id, token.address, mute_until
        self._save_mutelists_to_disk()

    def mute_for(self, user: User, token: Token, mute_for: Timestamp):
        self._set_mute_until(user, token, time.time() + mute_for)

    def mute_forever(self, user: User, token: Token):
        self._set_mute_until(user, token, None)
