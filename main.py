import asyncio
from collections.abc import Iterable
import logging
import time
from asyncio import CancelledError
from datetime import datetime, timedelta
from enum import Enum, auto

from telegram import error, Bot, Update, Message, LinkPreviewOptions, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, Defaults, CallbackQueryHandler
from telegram.ext.filters import UpdateFilter
from aiogram import html
from pytonapi import AsyncTonapi
from pytonapi.schema.jettons import JettonBalance

import network
import settings
import users
from gecko_terminal_api_wrapper import GeckoTerminalAPIWrapper
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


class Status(Enum):
    SUCCESS = auto()
    REMOVED = auto()
    BLOCK = auto()
    EXCEPTION = auto()


class ImpossibleAction(Exception): pass


class UnknownException(Exception): pass


class FilterOnlyFromID(UpdateFilter):
    def __init__(self, id: users.Id):
        super().__init__()
        self.id = id

    def filter(self, update: Update):
        if update.message.chat_id != self.id:
            user = update.message.from_user
            logger.warning(f'Someone else\'s is trying to use the bot: {user.id}/{user.username}/{user.full_name} - Message: {update.message.text}')
            return False
        return True


class FilterNotInBlacklist(UpdateFilter):
    def __init__(self, blacklist: set[users.Id]):
        super().__init__()
        self.blacklist = blacklist

    def filter(self, update: Update):
        if update.message.chat_id in self.blacklist:
            user = update.message.from_user
            logger.warning(f'Someone from blacklist is trying to use the bot: {user.id}/{user.username}/{user.full_name} - Message: {update.message.text}')
            return False
        return True


def pools_to_message(
        pools: Iterable[Pool],
        prefix: str | tuple[str, str] | None = None,
        postfix: str | tuple[str, str] | None = None,
        balance=None,
        change=None,
        line_width=settings.TELEGRAM_MESSAGE_MAX_WIDTH,
        message_max_length=settings.TELEGRAM_MESSAGE_MAX_LEN,
):
    message_pools = ''

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
        return message_pools + ('\n\n' if message_pools else '') + message_pool

    def get_full_message(message_pools):
        return '\n\n'.join(filter(bool, [prefix, message_pools, postfix]))

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

        m5 = format_number(pool.price_change.m5, 3, sign=True, percent=True, significant_figures=2)
        h1 = format_number(pool.price_change.h1, 4, sign=True, percent=True, significant_figures=2)
        h24 = format_number(pool.price_change.h24, 4, sign=True, percent=True, significant_figures=2)
        add_line('Price:', f'{m5} {h1} {h24}')

        m5 = format_number(round(pool.buyers_sellers_ratio.m5, 1), 4, 1)
        h1 = format_number(round(pool.buyers_sellers_ratio.h1, 1), 4, 1)
        h24 = format_number(round(pool.buyers_sellers_ratio.h24, 1), 4, 1)
        add_line('Buyers/sellers:', f'{m5} {h1} {h24}')

        add_line('Age:', pool.creation_date.difference_to_pretty_str())
        add_line('FDV:', format_number(pool.fdv, 6, symbol='$', k_mode=True))
        add_line('Volume:', format_number(pool.volume, 6, symbol='$', k_mode=True))
        add_line('Liquidity:', format_number(pool.liquidity, 6, symbol='$', k_mode=True))
        add_line('Transactions:', str(round_to_significant_figures(pool.transactions, 2)))
        add_line('Makers:', str(round_to_significant_figures(pool.makers, 2)))

        link_gecko = html.link('GeckoTerminal', f'https://www.geckoterminal.com/{settings.NETWORK}/pools/{pool.address}')
        link_dex = html.link('DEX Screener', f'https://dexscreener.com/{settings.NETWORK}/{pool.address}')
        if pool.dex.id == 'dedust':
            links_between_width = line_width - 22
            links = link_dex + html.code(spaces(links_between_width)) + link_gecko
        else:
            links = spaces(1) + html.code(spaces(10 + (line_width - 22))) + link_gecko

        message_pool = html.code('\n'.join(lines)) + '\n' + links
        new_message_pools = get_updated_message_pools(message_pool)

        if len(clear_from_html(get_full_message(new_message_pools))) <= message_max_length:
            message_pools = new_message_pools
        else:
            break

    return get_full_message(message_pools)


class TONSonar:
    def __init__(self):
        self.bot: Bot | None = None
        self.pools = Pools(pool_filter=settings.POOL_DEFAULT_FILTER, repeated_pool_filter_key=lambda p: p.volume)
        self.users: Users = Users()
        self.blacklist: set[users.Id] = settings.BLACKLIST_CHAT_ID
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

        message_filter = FilterNotInBlacklist(self.blacklist) if settings._RUNNING_MODE else FilterOnlyFromID(settings.DEVELOPER_CHAT_ID)
        application.add_handler(CommandHandler(settings.COMMAND_START, self.start, message_filter))
        application.add_handler(CommandHandler(settings.COMMAND_HELP, self.help, message_filter))
        application.add_handler(CommandHandler(settings.COMMAND_RESEND, self.resend, message_filter))
        application.add_handler(CallbackQueryHandler(self.buttons_mute))
        await self.bot.set_my_commands(settings.COMMAND_MENU)

        async with application:
            await application.start()
            await application.updater.start_polling()

            try:
                while True:
                    await self.run_one_cycle()
            except CancelledError as e:
                logger.info(f'Stopping the bot because of an exit signal{" - " + str(e) if str(e) else str(e)}')

            await application.updater.stop()
            await application.stop()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        id = update.message.chat_id

        if not self.users.has_user(id):
            user = update.message.from_user
            logger.warning(f'New user started the bot: {user.id}/{user.username}/{user.full_name}')
            self.users.add_user(id)

        await update.message.reply_text(settings.COMMAND_START_MESSAGE)

    @staticmethod
    async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(settings.COMMAND_HELP_MESSAGE)

    async def run_one_cycle(self):
        start_time = time.time()

        logger.info('Updating pools')
        self.pools.clear()
        await self.geckoterminal_api.update_pools(self.pools)
        logger.info(f'Pools: {len(self.pools)}, Tokens: {len(self.pools.get_tokens())}')

        await self.update_main_message()
        await self.send_pump_notification()

        cooldown = settings.UPDATES_COOLDOWN - (time.time() - start_time)
        if cooldown > 0:
            logger.info(f'Going to asynchronous sleep - {cooldown:.0f}s')
            await asyncio.sleep(cooldown)

    async def update_main_message(self):
        growing_pools = [p for p in self.pools if self.pool_score(p) > settings.GROWING_POOLS_MIN_SCORE]
        growing_pools.sort(key=self.pool_score, reverse=True)
        logger.info(f'Updating main message - Growing pools: {len(growing_pools)}')

        for user in self.users.get_users():
            user_pools = [p for p in growing_pools if not self.users.is_muted(user, p.base_token)]
            message = pools_to_message(
                user_pools,
                prefix='Growing pools',
                postfix=('', datetime.now().strftime('%d.%m.%Y, %H:%M:%S')),
            )

            if user_pools:
                main_message_id = self.users.get_property(user, Property.MAIN_MESSAGE_ID)
                sending = not bool(main_message_id)
                message, status = await self.send_or_edit_message(message, user, message_id=main_message_id, disable_notification=True)

                match status:
                    case Status.SUCCESS:

                        if sending:
                            await self.unpin_all_messages(user)
                            if await self.pin_message(user, message.message_id, disable_notification=True):
                                self.users.set_property(user, Property.MAIN_MESSAGE_ID, message.message_id)

                    case Status.REMOVED:
                        self.users.clear_property(user, Property.MAIN_MESSAGE_ID)

    async def resend(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.users.clear_property(self.users.get_user(update.message.chat_id), Property.MAIN_MESSAGE_ID)
        await self.update_main_message()

    async def send_pump_notification(self):
        pumped_pools_source = [p for p in self.pools if self.pool_score(p) > settings.PUMPED_POOLS_MIN_SCORE]
        pumped_pools_source.sort(key=self.pool_score, reverse=True)
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
                            if pool := self.pools.find_best_token_pool(token, key=lambda p: p.volume):

                                if not token_balance:
                                    user.add_token_balance(TokenBalance(token, amount=balance, rate=pool.price_in_native_currency))
                                    token.update(decimals=x.jetton.decimals)
                                else:
                                    change = pool.price_in_native_currency / token_balance.rate - 1

                                    if (
                                            abs(change) > settings.NOTIFICATION_USER_WALLET_CHANGE_BOUND and
                                            not self.users.is_muted(user, token)
                                    ):
                                        self.users.mute_for(user, token, settings.NOTIFICATION_COOLDOWN_WALLET)
                                        data.append((pool, change))
                                        token_balance.set(amount=balance, rate=pool.price_in_native_currency)
                                    else:
                                        token_balance.set(amount=balance)
                        elif token_balance:
                            user.remove_token_balance(token_balance)

            data.sort(key=lambda x: x[1], reverse=True)
            data = list(zip(*data))
            wallet_pools, change = (list(data[0]), list(data[1])) if data else ([], [])
            pumped_pools = []

            for pool in pumped_pools_source:
                if pool not in wallet_pools:
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
                    await self.send_message(message, user, reply_markup=self.reply_markup_mute)

    @staticmethod
    def pool_score(pool: Pool):
        return 3 * max(pool.price_change.m5 * 100, 0) + max(pool.price_change.h1 * 100, 0)

    async def send_message(self, text, user: User, **kwargs) -> tuple[Message | None, Status]:
        return await self.send_or_edit_message(text, user, **kwargs)

    async def edit_message(self, text, user: User, message_id: MessageID) -> tuple[Message | None, Status]:
        return await self.send_or_edit_message(text, user, message_id)

    async def send_or_edit_message(self, text, user: User, message_id: MessageID = None, **kwargs) -> tuple[Message | None, Status]:
        def to_info(str, append=None):
            return f'{str} - Chat ID: {user.id}' + (f'/{message_id}' if message_id else '') + (f' - {append}' if append else '')

        try:
            if not message_id:
                return await self.bot.send_message(user.id, text, **kwargs), Status.SUCCESS
            else:
                message = await self.bot.edit_message_text(text, user.id, message_id)
                if isinstance(message, Message):
                    return message, Status.SUCCESS
                else:
                    raise ImpossibleAction(to_info('You can\'t edit an inline message'))

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

    async def pin_message(self, user: User, message_id: MessageID, **kwargs) -> bool:
        if not await self.bot.pin_chat_message(user.id, message_id, **kwargs):
            logger.error(f'Can\'t pin the main message - Chat ID: {user.id}/{message_id}')
            return False
        return True

    async def unpin_all_messages(self, user: User) -> bool:
        try:
            if not await self.bot.unpin_all_chat_messages(user.id):
                logger.error(f'Can\'t unpin all chat messages - Chat ID: {user.id}')
                return False
            return True
        except error.TimedOut as e:
            logger.error(f'Can\'t unpin all chat messages - Chat ID: {user.id} - {e}')
            return False

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
