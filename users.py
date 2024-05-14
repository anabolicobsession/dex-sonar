import os
import time
from enum import Enum
from typing import Any

import pandas as pd

import settings
from network import Token


Id = int


class Timestamp:
    def __init__(self):
        self.timestamp = None

    def has_been_made(self):
        return self.timestamp is not None

    def make(self):
        self.timestamp = time.time()

    def seconds_passed(self):
        return time.time() - self.timestamp


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
        self.last_token_notifications: dict[Token, Timestamp] = {}

    def add_token_balance(self, token_balance: TokenBalance):
        self.token_balances[token_balance.token] = token_balance

    def get_token_balance(self, token: Token) -> TokenBalance | None:
        return self.token_balances.get(token, None)

    def remove_token_balance(self, token_or_token_balance: Token | TokenBalance):
        self.token_balances.pop(token_or_token_balance if isinstance(token_or_token_balance, Token) else token_or_token_balance.token)

    def get_last_token_notification(self, token: Token) -> Timestamp:
        if token not in self.last_token_notifications:
            self.last_token_notifications[token] = Timestamp()
        return self.last_token_notifications[token]


class Property(str, Enum):
    ID = 'id'
    MAIN_MESSAGE_ID = 'main_message_id'
    WALLET = 'wallet'


property_dtypes = {
    Property.ID: 'int',
    Property.MAIN_MESSAGE_ID: 'int',
    Property.WALLET: 'str',
}


class Users:
    def __init__(self):
        self.users: dict[Id, User] = {}
        self.user_database = pd.DataFrame(
            index=pd.Series(name=Property.ID, dtype=property_dtypes[Property.ID]),
            data={k: pd.Series(dtype=v) for k, v in property_dtypes.items() if k is not Property.ID}
        )

        if os.path.isfile(settings.DATABASES_PATH_USERS):
            self.user_database = pd.read_csv(settings.DATABASES_PATH_USERS, index_col=0, dtype=property_dtypes).astype(object)

            for id in self.user_database.index:
                self.users[id] = User(id)

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
        self.user_database.loc[id] = pd.NA
        self._save_user_database_to_disk()

    def remove_user(self, id: Id):
        self.users.pop(id)
        self.user_database.drop(index=id, inplace=True)
        self._save_user_database_to_disk()

    def set_property(self, user: User, property: Property, value):
        self.user_database.loc[user.id, property] = value
        self._save_user_database_to_disk()

    def clear_property(self, user: User, property: Property):
        self.user_database.loc[user.id, property] = pd.NA
        self._save_user_database_to_disk()

    def has_property(self, user: User, property: Property):
        return not pd.isna(self.user_database.loc[user.id, property])

    def get_property(self, user: User, property: Property):
        return self.user_database.loc[user.id, property]

    def get_property_if_exists(self, user: User, property: Property) -> Any | None:
        return self.user_database.loc[user.id, property] if self.has_property(user, property) else None
