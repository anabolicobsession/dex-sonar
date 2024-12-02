import logging
from asyncio import CancelledError
from os import environ

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from dex_sonar.auxiliary.logs import setup_logging
from dex_sonar.auxiliary.time import Cooldown, Timedelta, Timestamp
from dex_sonar.bot import Bot
from dex_sonar.config.config import TESTING_MODE, config
from dex_sonar.message import Message, Type as MessageType
from dex_sonar.network.network import Token
from network.pool_with_chart.pool_with_chart import Pool
from dex_sonar.pools.pools_with_api import PoolsWithAPI
from dex_sonar.users import Users


setup_logging()
logger = logging.getLogger(__name__)


class Application:
    def __init__(self):
        self.bot = Bot(
            token=environ.get('BOT_TOKEN') if not TESTING_MODE else environ.get('TESTING_BOT_TOKEN'),
            token_silent=environ.get('SILENT_BOT_TOKEN') if not TESTING_MODE else environ.get('TESTING_SILENT_BOT_TOKEN'),
        )
        self.pools = PoolsWithAPI(
            additional_cooldown=Timedelta.from_other(config.get_timedelta_from_seconds('Updates', 'additional_cooldown')),
            update_callback=self.update_callback,

            do_intermediate_updates=config.getboolean('Updates', 'do_intermediate_updates'),
            intermediate_update_duration=(
                Timedelta.from_other(config.get_timedelta_from_seconds('Updates', 'intermediate_update_duration'))
                if config.has_option('Updates', 'intermediate_update_duration')
                else None
            ),
            starting_intermediate_update_duration_estimate=Timedelta.from_other(config.get_timedelta_from_seconds('Updates', 'starting_intermediate_update_duration_estimate')),

            fetch_new_pools_every_update=config.getint('Updates', 'fetch_new_pools_every_update'),
            dex_screener_delay=Timedelta.from_other(config.get_timedelta_from_seconds('Screeners', 'dex_screener_delay')),

            pool_filter=(
                lambda x:
                x.liquidity >= config.getint('Pools', 'min_liquidity') and
                x.volume >= config.getint('Pools', 'min_volume')
            ),

            request_error_cooldown=Cooldown(
                cooldown=Timedelta(seconds=0.9375),  # 60 / 64 (binary powers of a minute)
                multiplier=2,
                within_time_period=Timedelta(minutes=20),
            ),
        )
        self.users: Users = Users()
        self.pool_last_arbitrage: dict[Pool, (Timestamp, float)] = {}

        self.bot.add_handlers([
            CallbackQueryHandler(self.serve_mute_button),
        ])
        self.reply_markup_mute = InlineKeyboardMarkup([[
            InlineKeyboardButton('1 day', callback_data='1'),
            InlineKeyboardButton('3 days', callback_data='3'),
            InlineKeyboardButton('1 week', callback_data='7'),
            InlineKeyboardButton('Forever', callback_data='-1'),
        ]])
        self.reply_markup_unmute = InlineKeyboardMarkup([[
            InlineKeyboardButton('Unmute', callback_data='0'),
        ]])

    def run(self):
        self.bot.run(self._run())

    async def _run(self):
        try:
            while True: await self.pools.update_via_api()

        except CancelledError:
            logger.info(f'Stopping the bot')

        finally:
            await self.remove_status()
            await self.pools.close_api_sessions()
            self.users.close_connection()

    async def update_status(self):
        await self.bot.set_description(f'Live. Uptime: {self.pools.get_uptime().to_human_readable_format(minimum=Timedelta.MINUTE)}')

    async def remove_status(self):
        await self.bot.remove_description()

    async def update_callback(self, main_update=False):
        if main_update: await self.update_status()
        await self.send_messages_if_patterns_detected()
        await self.send_messages_if_arbitrage_possible()

    async def send_messages_if_patterns_detected(self):
        tuples = []

        for pool in self.pools:
            if match := pool.chart.get_pattern(only_new=True):
                if pool.chart.can_be_plotted():
                    tuples.append((
                        pool,
                        match,
                        Message(
                            type=MessageType.PATTERN,
                            pool=pool,
                            attention_text=f'{match.pattern.get_name()} {match.magnitude:.0%}',
                        ),
                    ))

        if tuples:
            tuples.sort(key=lambda x: x[1].magnitude, reverse=True)
            tickers = [x[0].base_token.ticker for x in tuples]
            logger.info(f'Detected pools with patterns: {", ".join(tickers)} - Sending messages (if a token is not muted)')
        else:
            return

        for user_id in self.users.get_user_ids():
            for pool, match, message in tuples:
                if not self.users.is_muted(user_id, pool.base_token):
                    await self.bot.send_message(user_id, message, reply_markup=self.reply_markup_mute, silent=not match.significant)

    async def send_messages_if_arbitrage_possible(self):
        for pool in self.pools:

            for similar_pool in self.pools.get_pools_with_same_base_token(pool):

                similar_pool: Pool
                price_difference = abs(pool.price_usd / similar_pool.price_usd - 1)

                if price_difference >= config.get_normalized_percent('Arbitrage', 'price_min_difference'):

                    if pool.price_usd < similar_pool.price_usd:
                        pool_to_buy = pool
                        pool_to_sell = similar_pool
                    else:
                        pool_to_buy = similar_pool
                        pool_to_sell = pool

                    is_pool_to_buy = pool_to_buy in self.pool_last_arbitrage
                    is_pool_to_sell = pool_to_sell in self.pool_last_arbitrage

                    if is_pool_to_buy or is_pool_to_sell:

                        if is_pool_to_buy ^ is_pool_to_sell:
                            arbitrage_pool = pool_to_buy if pool_to_buy in self.pool_last_arbitrage else pool_to_sell
                        else:
                            pool_to_buy_was_later = self.pool_last_arbitrage[pool_to_buy][0] >= self.pool_last_arbitrage[pool_to_sell][0]
                            arbitrage_pool = pool_to_buy if pool_to_buy_was_later else pool_to_sell

                        timestamp, previous_price = self.pool_last_arbitrage[arbitrage_pool]

                        if timestamp.time_elapsed() < Timedelta(minutes=30) or arbitrage_pool.price_usd == previous_price:
                            continue

                    if pool_to_buy.chart.can_be_plotted():

                        self.pool_last_arbitrage[pool_to_buy] = Timestamp.now(), pool_to_buy.price_usd
                        message = Message(
                            type=MessageType.ARBITRAGE,
                            pool=pool_to_buy,
                            additional_pool=pool_to_sell,
                            attention_text=f'Arbitrage {price_difference:.0%}',
                        )
                        logger.info(
                            f'Detected arbitrage pools: '
                            f'{pool_to_buy.base_ticker} / '
                            f'{pool_to_buy.quote_ticker} ({pool_to_buy.dex_name}) -> {pool_to_sell.quote_ticker} ({pool_to_sell.dex_name})'
                        )

                        for user in self.users.get_user_ids():
                            if not self.users.is_muted(user, pool_to_buy.base_token):
                                await self.bot.send_message(user, message, reply_markup=self.reply_markup_mute)

    def _parse_token(self, token_ticker: str) -> Token | None:
        matches = [t for t in self.pools.get_tokens() if t.ticker.lower() == token_ticker.lower()]

        if len(matches) == 0:
            logger.warning(f'There is no {token_ticker} token')
        elif len(matches) > 1:
            logger.warning(f'There are multiple tokens with ticker {token_ticker}, picking the first one')

        return matches[0] if len(matches) >= 1 else None

    async def serve_mute_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        option = int(query.data)
        user_id = query.message.chat.id

        if option:
            token_address = query.message.caption.rsplit('\n', 1)[-1]
            matches = [t for t in self.pools.get_tokens() if t.address == token_address]

            if matches:
                token = matches[0]
            else:
                token = None
                logger.warning(f'Can\'t find token by address: {token_address}')
        else:
            token = self._parse_token(query.message.caption.split(' ', 3)[2])

        # callback query need to be answered, even if no notification to the user is needed, some clients may have trouble otherwise
        await query.answer()

        if not token:
            await self.bot.send_message(
                user_id,
                'Sorry, unable to do this action in the current program version',
                silent=context.bot,
            )
            return

        if option:
            if option > 0:
                self.users.mute_for(user_id, token, Timedelta(days=option))
            else:
                self.users.mute_forever(user_id, token)

            duration = f'for {option} day{"" if option == 1 else "s"}' if option > 0 else 'forever'
            await query.edit_message_caption(
                caption=f'Successfully muted {token.ticker} {duration}',
                reply_markup=self.reply_markup_unmute
            )
        else:
            self.users.unmute(user_id, token)
            await query.edit_message_caption(
                caption=f'{token.ticker} was unmuted',
            )


if __name__ == '__main__':
    Application().run()
