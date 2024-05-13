import os
import time

import pandas as pd

import settings
from pools import Token, Pools


Id = int
Address = str


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
        self.timestamp = Timestamp()

    def update(self, amount=None, rate=None):
        if amount: self.amount = amount
        if rate: self.rate = rate

    def calculate_balance(self):
        return self.amount * 10 ** -self.token.decimals * self.rate


class User:
    def __init__(self, id, wallet: Address):
        self.id: Id = id
        self.wallet = wallet
        self.token_balances: dict[Token, TokenBalance] = {}
        self.last_token_notifications: dict[Token, Timestamp] = {}

    def update_token_balance(self, token: Token, **data):
        if token not in self.token_balances:
            self.token_balances[token] = TokenBalance(token, **data)
        else:
            self.token_balances[token].update(**data)

    def get_token_balance(self, token: Token) -> TokenBalance | None:
        return self.token_balances.get(token, None)

    def remove_token_balance(self, token_or_token_balance: Token | TokenBalance):
        self.token_balances.pop(token_or_token_balance if isinstance(token_or_token_balance, Token) else token_or_token_balance.token)

    def get_last_token_notification(self, token: Token) -> Timestamp:
        if token not in self.last_token_notifications:
            self.last_token_notifications[token] = Timestamp()
        return self.last_token_notifications[token]


class Users:
    def __init__(self):
        self.users: dict[Id, User] = {
        }
        self.pinned_messages_ids = pd.DataFrame({'user_id': pd.Series(dtype='int'), 'pinned_message_id': pd.Series(dtype='int')})
        self.pinned_messages_ids.set_index('user_id', inplace=True)
        self.followlists = pd.DataFrame({'user_id': pd.Series(dtype='int'), 'token_address': pd.Series(dtype='str')})
        self._init()

    def _init(self):
        if os.path.isfile(settings.PINNED_MESSAGES_IDS_PATH):
            self.pinned_messages_ids = pd.read_csv(settings.PINNED_MESSAGES_IDS_PATH, index_col=0)
        if os.path.isfile(settings.FOLLOWLISTS_PATH):
            self.followlists = pd.read_csv(settings.FOLLOWLISTS_PATH)

    def get_users(self) -> list[User]:
        return list(self.users.values())

    def get_user(self, id: Id) -> User:
        return self.users[id]

    def set_pinned_message_id(self, user: User, id: Id):
        self.pinned_messages_ids.loc[user.id] = id
        self.pinned_messages_ids.to_csv(settings.PINNED_MESSAGES_IDS_PATH)

    def remove_pinned_message_id(self, user: User):
        self.pinned_messages_ids.drop(user.id, inplace=True)
        self.pinned_messages_ids.to_csv(settings.PINNED_MESSAGES_IDS_PATH)

    def has_pinned_message_id(self, user: User):
        return user.id in self.pinned_messages_ids.index

    def get_pinned_message_id(self, user: User):
        return self.pinned_messages_ids.loc[user.id].item()

    def add_to_followlist(self, user: User, token: Token):
        self.followlists.loc[len(self.followlists.index)] = user.id, token.address
        self.followlists.to_csv(settings.FOLLOWLISTS_PATH, index=False)

    def remove_from_followlist(self, user: User, token: Token):
        idx = self.followlists[(self.followlists['user_id'] == user.id) & (self.followlists['token_address'] == token.address)].index
        self.followlists.drop(idx, inplace=True)
        self.followlists.to_csv(settings.FOLLOWLISTS_PATH, index=False)

    def get_followlist(self, user: User, pools: Pools) -> list[Token]:
        return [pools.get_token(a) for a in self.followlists.loc[self.followlists['user_id'] == user.id]['token_address'].to_list()]
