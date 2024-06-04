import asyncio
from collections.abc import Iterable
import logging
import time
from asyncio import CancelledError
from datetime import timedelta, datetime
from enum import Enum, auto

from telegram import error, Bot, Update, Message, LinkPreviewOptions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, Defaults, CallbackQueryHandler, CommandHandler
from telegram.ext.filters import UpdateFilter
from aiogram import html
from pytonapi import AsyncTonapi
from pytonapi.schema.jettons import JettonBalance

import network
import settings
import users
from gecko_api import GeckoTerminalAPIWrapper
from network import Pools, Pool
from users import User, Users, Property, TokenBalance
from utils import format_number, round_to_significant_figures, clear_from_html


root_logger = logging.getLogger()
root_logger.setLevel(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logging_formatter = logging.Formatter(settings.LOGGING_FORMAT)

handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
handler.setFormatter(logging_formatter)
root_logger.addHandler(handler)

handler = logging.FileHandler(settings.LOGGING_PATH_WARNINGS, mode='w')
handler.setLevel(logging.WARNING)
handler.setFormatter(logging_formatter)
root_logger.addHandler(handler)

handler = logging.FileHandler(settings.LOGGING_PATH_DEBUG, mode='w')
handler.setLevel(logging.DEBUG)
handler.setFormatter(logging_formatter)
root_logger.addHandler(handler)

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore.http11').setLevel(logging.INFO)
logging.getLogger('httpcore.connection').setLevel(logging.INFO)


MessageID = int


def pools_to_message(
        pools: Iterable[Pool],
        prefix: str | tuple[str, str] | None = None,
        postfix: str | tuple[str, str] | None = None,
        balance=None,
        change=None,
        line_width=settings.TELEGRAM_MESSAGE_MAX_WIDTH,
        message_max_length=settings.TELEGRAM_MESSAGE_MAX_LEN,
):
    pool_message = ''

    def spaces(n):
        return ' ' * n

    def fit_prefix_or_postfix(x):
        if x:
            if isinstance(x, str):
                return html.code(spaces((line_width - len(x)) // 2) + x)
            else:
                left, right = x
                return html.code(left + spaces(line_width - (len(left) + len(right))) + right)
        return None

    prefix, postfix = fit_prefix_or_postfix(prefix), fit_prefix_or_postfix(postfix)

    def get_updated_message_pools(message_pool):
        return pool_message + ('\n\n' if pool_message else '') + message_pool

    def get_full_message(pool_message):
        return '\n\n'.join(filter(bool, [prefix, pool_message, postfix]))

    def add_line(str1, str2):
        lines.append(f'{str1}{spaces(line_width - (len(str1) + len(str2)))}{str2}')

    for i, pool in enumerate(pools):
        lines = []

        add_line(
            pool.base_token.ticker if pool.quote_token.is_native_currency() else pool.base_token.ticker + '/' + pool.quote_token.ticker,
            format_number(pool.price, 4, 9, symbol='$', significant_figures=2)
        )

        if balance and balance[i]: add_line('Balance:', f'{round_to_significant_figures(balance[i], 3)} {settings.NETWORK.upper()}')
        if change and change[i]: add_line('Change:', format_number(change[i], 4, sign=True, percent=True, significant_figures=2))

        left = 3

        m5 = format_number(pool.price_change.m5, left, sign=True, percent=True, significant_figures=2)
        h1 = format_number(pool.price_change.h1, left, sign=True, percent=True, significant_figures=2)
        h6 = format_number(pool.price_change.h6, left, sign=True, percent=True, significant_figures=2)
        add_line('Price:', f'{m5} {h1} {h6}')

        for name, timedata in [('Buyers/Sellers:', pool.buyers_sellers_ratio), ('Volume ratio:', pool.volume_ratio)]:
            m5 = format_number(round(timedata.m5, 1),  left, 1)
            h1 = format_number(round(timedata.h1, 1), left, 1)
            h6 = format_number(round(timedata.h6 if name != 'Buyers/Sellers:' else timedata.h24, 1),  left, 1)
            add_line(name, f'{m5} {h1} {h6}')

        add_line('Volume:', format_number(pool.volume, 6, symbol='$', k_mode=True))
        add_line('Liquidity:', format_number(pool.liquidity, 6, symbol='$', k_mode=True))
        add_line('Makers:', str(round_to_significant_figures(pool.makers, 2)))
        add_line('TXNs/Makers:', format_number(round(pool.transactions / pool.makers, 1), 3, 1))
        add_line('Volume/Liquidity:', format_number(round(pool.volume / pool.liquidity, 1), 3, 1))
        add_line('FDV/Liquidity:', format_number(round(pool.fdv / pool.liquidity, 1), 3, 1))
        add_line('Age:', pool.creation_date.difference_to_pretty_str())

        link_gecko = html.link('GeckoTerminal', f'https://www.geckoterminal.com/{settings.NETWORK}/pools/{pool.address}')
        link_dex = html.link('DEX Screener', f'https://dexscreener.com/{settings.NETWORK}/{pool.address}')
        links = link_dex + html.code(spaces(line_width - 22)) + link_gecko

        new_pool_message = get_updated_message_pools(html.code('\n'.join(lines)) + '\n' + links + '\n' + html.code(pool.base_token.address))

        if len(clear_from_html(get_full_message(new_pool_message))) <= message_max_length:
            pool_message = new_pool_message
        else:
            break

    return get_full_message(pool_message)


class Status(Enum):
    SUCCESS = auto()
    REMOVED = auto()
    BLOCK = auto()
    EXCEPTION = auto()


class ImpossibleAction(Exception): pass


class UnknownException(Exception): pass


class FilterWhitelist(UpdateFilter):
    def __init__(self, whitelist: set[users.Id]):
        super().__init__()
        self.whitelist = whitelist

    def filter(self, update: Update):
        if update.message.chat_id not in self.whitelist:
            user = update.message.from_user
            logger.warning(f'Someone else\'s is trying to use the bot: {user.id}/{user.username}/{user.full_name} - Message: {update.message.text}')
            return False
        return True


class TONSonar:
    def __init__(self):
        self.bot: Bot | None = None
        self.pools = Pools(pool_filter=settings.POOL_DEFAULT_FILTER, repeated_pool_filter_key=lambda p: p.volume)
        self.users: Users = Users()
        self.geckoterminal_api = GeckoTerminalAPIWrapper(max_requests=settings.GECKO_TERMINAL_MAX_REQUESTS_PER_CYCLE)
        self.ton_api = AsyncTonapi(api_key=settings.TON_API_KEY)

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
        asyncio.run(self.run_event_loop())

    async def run_event_loop(self):
        defaults = Defaults(parse_mode=ParseMode.HTML, link_preview_options=LinkPreviewOptions(is_disabled=True))
        application = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).defaults(defaults).build()
        self.bot = application.bot

        message_filter = FilterWhitelist(settings.WHITELIST_CHAT_ID if settings.PRODUCTION_MODE else [settings.DEVELOPER_CHAT_ID])
        application.add_handler(CommandHandler('start', self.start, message_filter))
        application.add_handler(CallbackQueryHandler(self.buttons_mute))

        async with application:
            await application.start()
            await application.updater.start_polling()

            try:
                while True:
                    await self.run_one_cycle()
            except CancelledError as e:
                logger.info(f'Stopping the bot{" - " + str(e) if str(e) else str(e)}')
                await self.geckoterminal_api.close()

            await application.updater.stop()
            await application.stop()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        id = update.message.chat_id

        if not self.users.has_user(id):
            user = update.message.from_user
            logger.warning(f'New user started the bot: {user.id}/{user.username}/{user.full_name}')
            self.users.add_user(id)
            await update.message.reply_text('You\'ve subscribed to growing pool updates')
        else:
            await update.message.reply_text('You already subscribed')

    async def run_one_cycle(self):
        start_time = time.time()

        logger.info('Updating pools')
        self.pools.clear()
        await self.geckoterminal_api.update_pools(self.pools)
        logger.info(f'Pools: {len(self.pools)}, Tokens: {len(self.pools.get_tokens())}')

        await self.send_pump_notification()
        await self.bot.set_my_short_description(f'Last update: {datetime.now().strftime("%I:%M %p")}')

        cooldown = settings.UPDATES_COOLDOWN - (time.time() - start_time)
        if cooldown > 0:
            logger.info(f'Going to asynchronous sleep - {cooldown:.0f}s')
            await asyncio.sleep(cooldown)

    async def send_pump_notification(self):
        pumped_pools_source = [p for p in self.pools if settings.should_be_notified(p)]
        pumped_pools_source.sort(key=settings.calculate_change_score, reverse=True)
        logger.info(f'Sending pump notification - Pumped pools: {len(pumped_pools_source)}')

        async def get_jetton_balances(user: User, wallet: network.Address) -> list[JettonBalance] | None:
            try:
                return (await self.ton_api.accounts.get_jettons_balances(wallet)).balances

            except AttributeError as e:
                logger.error(f'Exception occurred during using TON API - Chat ID: {user.id} - {e}')
                return None

        for user in self.users.get_users():
            data = []

            if wallet := self.users.get_property(user, Property.WALLET):
                if jetton_balances := await get_jetton_balances(user, wallet):
                    for x in jetton_balances:
                        balance = int(x.balance)
                        token = self.pools.get_token(x.jetton.address.to_userfriendly(is_bounceable=True))
                        token_balance = user.get_token_balance(token)

                        if balance and token:
                            pool: Pool = self.pools.find_best_token_pool(token, key=lambda p: p.volume)

                            if pool:
                                user.wallet_tokens.add(token)


                                if not token_balance:
                                    user.add_token_balance(TokenBalance(token, amount=balance, rate=pool.price_in_native_token))
                                    token.update(decimals=x.jetton.decimals)
                                else:
                                    change = pool.price_in_native_token / token_balance.rate - 1

                                    if (
                                            balance * 10 ** -x.jetton.decimals * pool.price_in_native_token > settings.MIN_BALANCE and
                                            (
                                                    change < -settings.CHANGE_BOUND_LOW or
                                                    change > settings.CHANGE_BOUND_HIGH
                                            ) and
                                            not self.users.is_muted(user, token)
                                    ):
                                        print(token, change, token_balance.rate, pool.price_in_native_token, pool.price_in_native_token)
                                        self.users.mute_for(user, token, settings.NOTIFICATION_COOLDOWN_WALLET)
                                        data.append((pool, change))
                                        token_balance.set(amount=balance, rate=pool.price_in_native_token)
                                    else:
                                        token_balance.set(amount=balance)

                        elif token_balance:
                            user.remove_token_balance(token_balance)

            data.sort(key=lambda x: x[1], reverse=True)
            data = list(zip(*data))
            wallet_pools, change = (list(data[0]), list(data[1])) if data else ([], [])
            pumped_pools = []

            for pool in pumped_pools_source:
                if pool.base_token not in user.wallet_tokens:
                    if not self.users.is_muted(user, pool.base_token):
                        self.users.mute_for(user, pool.base_token, settings.NOTIFICATION_PUMP_COOLDOWN)
                        pumped_pools.append(pool)

            pools = [*wallet_pools, *pumped_pools]
            balances = [user.get_token_balance(p.base_token).calculate_balance() for p in wallet_pools] + [None] * len(pumped_pools)
            changes = change + [None] * len(pumped_pools)

            if pools:
                for i, pool in enumerate(pools):
                    message = pools_to_message(
                        [pool],
                        balance=[balances[i]],
                        change=[changes[i]],
                    )
                    _, status = await self.send_message(message, user, reply_markup=self.reply_markup_mute)

                    if status is Status.BLOCK:
                        break

    async def send_message(self, text, user: User, **kwargs) -> tuple[Message | None, Status]:
        def to_info(str, append=None):
            return f'{str} - Chat ID: {user.id}' + (f' - {append}' if append else '')

        try:
            return await self.bot.send_message(user.id, text, **kwargs), Status.SUCCESS

        except error.Forbidden as e:
            if str(e) == settings.TELEGRAM_FORBIDDEN_BLOCK:
                logger.info(to_info(f'User blocked the bot, removing from the database'))
                self.users.remove_user(user.id)
                return None, Status.BLOCK
            else:
                raise UnknownException(e)

        except error.BadRequest as e:
            match str(e):
                case settings.TELEGRAM_MESSAGE_TO_EDIT_NOT_FOUND:
                    logger.warning(to_info(e))
                    return None, Status.REMOVED

                case settings.TELEGRAM_BAD_REQUEST_MESSAGE_IS_NOT_MODIFIED:
                    logger.error(to_info(e))
                    return None, Status.EXCEPTION

                case settings.TELEGRAM_BAD_REQUEST_MESSAGE_IS_TOO_LONG:
                    logger.error(to_info(e, f'{len(clear_from_html(text))} chars'))
                    return None, Status.EXCEPTION

                case settings.TELEGRAM_CHAT_NOT_FOUND:
                    logger.warning(to_info(e))
                    return None, Status.EXCEPTION

                case _:
                    raise UnknownException(e)

        except error.TimedOut as e:
            logging.warning(to_info(e))
            return None, Status.EXCEPTION

    def _parse_token(self, token_ticker: str) -> network.Token | None:
        matches = [t for t in self.pools.get_tokens() if t.ticker.lower() == token_ticker.lower()]

        if len(matches) == 0:
            logger.warning(f'There is no {token_ticker} token')
        elif len(matches) > 1:
            logger.warning(f'There are multiple tokens with ticker {token_ticker}, picking the first one')

        return matches[0] if len(matches) >= 1 else None

    async def buttons_mute(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        option = int(query.data)
        user = self.users.get_user(query.message.chat.id)
        token = self._parse_token(query.message.text.split(' ', 3)[0 if option else 2])
        await query.answer()

        if not token:
            await self.send_message('Sorry, unable to do this action in the current program version', user, disable_notification=True)
            return

        if option:
            if option > 0:
                self.users.mute_for(user, token, timedelta(days=option).total_seconds())
            else:
                self.users.mute_forever(user, token)

            duration = f'for {option} day{"" if option == 1 else "s"}' if option > 0 else 'forever'
            await query.edit_message_text(text=f'Successfully muted {token.ticker} {duration}', reply_markup=self.reply_markup_unmute)
        else:
            self.users.unmute(user, token)
            await query.edit_message_text(text=f'{token.ticker} was unmuted')


if __name__ == '__main__':
    TONSonar().run()
