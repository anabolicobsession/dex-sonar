import os
from datetime import datetime, timedelta

import psycopg2
import pytz

import settings
from .network.network import Token


UserId = int


class Users:
    def __init__(self):
        self.connection = psycopg2.connect(os.environ.get('DATABASE_URL'), sslmode='require')
        self.connection.set_session(autocommit=True)
        self._create_tables_if_dont_exist()

    def close_connection(self):
        self.connection.close()

    def _create_tables_if_dont_exist(self):
        with self.connection.cursor() as c:
            c.execute(
                f'''
                CREATE TABLE IF NOT EXISTS {settings.DATABASE_NAME_USERS} (
                    user_id BIGINT PRIMARY KEY,
                    is_developer BOOLEAN NOT NULL DEFAULT FALSE
                );

                CREATE TABLE IF NOT EXISTS {settings.DATABASE_NAME_MUTELISTS} (
                    user_id BIGINT,
                    token_address CHAR(48),
                    mute_until TIMESTAMP,

                    PRIMARY KEY (user_id, token_address)
                );
                '''
            )

    def get_user_ids(self) -> list[int]:
        with self.connection.cursor() as c:
            c.execute(
                f'''
                    SELECT user_id FROM {settings.DATABASE_NAME_USERS};
                '''
                if settings.PRODUCTION_MODE else
                f'''
                    SELECT user_id FROM {settings.DATABASE_NAME_USERS} WHERE is_developer = TRUE;
                '''
            )
            return [r[0] for r in c.fetchall()]

    def get_developer_ids(self) -> list[int]:
        with self.connection.cursor() as c:
            c.execute(
                f'''
                    SELECT user_id FROM {settings.DATABASE_NAME_USERS};
                '''
            )
            return [r[0] for r in c.fetchall()]

    def _if_mute_record_exists(self, user_id: UserId, token: Token):
        with self.connection.cursor() as c:
            c.execute(
                f'''
                    SELECT EXISTS(
                        SELECT 1
                        FROM {settings.DATABASE_NAME_MUTELISTS}
                        WHERE user_id = %s and token_address = %s
                    )  
                ''',
                (user_id, token.address)
            )
            return c.fetchone()[0]

    def _get_mute_until(self, user_id: UserId, token: Token) -> datetime | None:
        with self.connection.cursor() as c:
            c.execute(
                f'''
                    SELECT mute_until
                    FROM {settings.DATABASE_NAME_MUTELISTS}
                    WHERE user_id = %s and token_address = %s;
                ''',
                (user_id, token.address)
            )
            return c.fetchone()[0]

    def is_muted(self, user_id: UserId, token: Token):
        if self._if_mute_record_exists(user_id, token):
            datetime_or_none = self._get_mute_until(user_id, token)
            return not datetime_or_none or datetime.now(pytz.utc) < pytz.utc.localize(datetime_or_none)
        return False

    def _set_mute_until(self,  user_id: UserId, token: Token, mute_until: datetime | None):
        with self.connection.cursor() as c:
            c.execute(
                f'''
                    INSERT INTO {settings.DATABASE_NAME_MUTELISTS}
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, token_address)
                    DO UPDATE SET mute_until = EXCLUDED.mute_until
                    WHERE {settings.DATABASE_NAME_MUTELISTS}.user_id = %s and {settings.DATABASE_NAME_MUTELISTS}.token_address = %s;
                ''',
                (user_id, token.address, mute_until, user_id, token.address)
            )

    def mute_for(self, user_id: UserId, token: Token, mute_for: timedelta):
        self._set_mute_until(user_id, token, datetime.now(pytz.utc) + mute_for)

    def mute_forever(self, user_id: UserId, token: Token):
        self._set_mute_until(user_id, token, None)

    def unmute(self, user_id: UserId, token: Token):
        with self.connection.cursor() as c:
            c.execute(
                f'''
                    DELETE FROM {settings.DATABASE_NAME_MUTELISTS}
                    WHERE user_id = %s AND token_address = %s;
                ''',
                (user_id, token.address)
            )
