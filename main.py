import asyncio
from collections.abc import Iterable
import logging
import os
import time
from asyncio import CancelledError
from datetime import datetime

from pytonapi import AsyncTonapi
from pytonapi.schema.jettons import JettonBalance
from telegram import error, Bot, Update, Message
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from aiogram import html

import settings
from gecko_terminal_api_wrapper import GeckoTerminalAPIWrapper
from pools import Pools, Pool, Token
from users import User, Users
from utils import format_number, round_to_significant_figures, clear_from_html

logging.basicConfig(format=settings.LOGGING_FORMAT, level=settings.LOGGING_LEVEL)
logging.getLogger("httpx").setLevel(logging.WARNING)  # set higher logging level for httpx to avoid all GET and POST requests being logged
logger = logging.getLogger(__name__)

file_handler = logging.FileHandler(settings.LOGGING_WARNINGS_PATH, mode='w')
file_handler.setLevel(logging.WARNING)
file_handler.setFormatter(logging.Formatter(settings.LOGGING_FORMAT))
logger.addHandler(file_handler)


def pools_to_message(
        pools: Iterable[Pool],
        prefix: str | tuple[str, str] | None = None,
        postfix: str | tuple[str, str] | None = None,
        message_before=None,
        line_width=36,
        message_max_length=settings.TELEGRAM_MESSAGE_MAX_LEN,
        balance=None,
        change=None,
        age=False,
        fdv=False,
        volume=False,
        liquidity=False,
        transactions=False,
        makers=False,
        txs_per_wallet=False,
        price_change=False,
        buys_sells_change=False,
        buyers_sellers_change=False,
):
    message_pools = ''

    def spaces(n):
        return ' ' * n

    if prefix:
        if isinstance(prefix, str):
            prefix = html.code(spaces((line_width - len(prefix)) // 2) + prefix)
        else:
            left, right = prefix
            prefix = html.code(left + spaces(line_width - (len(left) + len(right))) + right)

    if postfix:
        if isinstance(postfix, str):
            postfix = html.code(spaces((line_width - len(postfix)) // 2) + postfix)
        else:
            left, right = postfix
            postfix = html.code(left + spaces(line_width - (len(left) + len(right))) + right)

    def get_updated_message_pools(message_pool):
        return message_pools + ('\n\n' if message_pools else '') + message_pool

    def get_full_message(message_pools):
        return '\n\n'.join(filter(bool, [message_before, prefix, message_pools, postfix]))

    def add_line(str1, str2):
        lines.append(f'{str1}{spaces(line_width - (len(str1) + len(str2)))}{str2}')

    for i, pool in enumerate(pools):
        lines = []

        add_line(
            pool.base_token.ticker if pool.quote_token.is_native_currency() else pool.base_token.ticker + '/' + pool.quote_token.ticker,
            format_number(pool.price, 4, 9, symbol='$', significant_figures=2)
        )

        if balance: add_line('Balance:', f'{round_to_significant_figures(balance[i], 3)} {settings.NETWORK.upper()}')
        if change: add_line('Change:', format_number(change[i], 4, sign=True, percent=True, significant_figures=2))
        if age: add_line('Age:', pool.creation_date.difference_to_pretty_str())
        if fdv: add_line('FDV:', format_number(pool.fdv, 6, symbol='$', k_mode=True))
        if volume: add_line('Volume:', format_number(pool.volume, 6, symbol='$', k_mode=True))
        if liquidity: add_line('Liquidity:', format_number(pool.liquidity, 6, symbol='$', k_mode=True))
        if transactions: add_line('Transactions:', str(round_to_significant_figures(pool.transactions, 2)))
        if makers: add_line('Makers:', str(round_to_significant_figures(pool.makers, 2)))
        if txs_per_wallet: add_line('TXs/wallet', str(round_to_significant_figures(pool.transactions_per_wallet, 2)))

        if price_change:
            m5 = format_number(pool.price_change.m5, 3, sign=True, percent=True, significant_figures=2)
            h1 = format_number(pool.price_change.h1, 4, sign=True, percent=True, significant_figures=2)
            h24 = format_number(pool.price_change.h24, 4, sign=True, percent=True, significant_figures=2)
            add_line('Price:', f'{m5} {h1} {h24}')

        tuples = []
        if buys_sells_change: tuples.append(('Buys/sells:', pool.buys_sells_ratio))
        if buyers_sellers_change: tuples.append(('Buyers/sellers:', pool.buyers_sellers_ratio))
        for name, td in tuples:
            m5 = format_number(round(td.m5, 1), 4, 1)
            h1 = format_number(round(td.h1, 1), 4, 1)
            h24 = format_number(round(td.h24, 1), 4, 1)
            add_line(name, f'{m5} {h1} {h24}')

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

    if not message_pools:
        prefix = None
        postfix = None

    return get_full_message(message_pools)


class DEXScanner:
    def     __init__(self):
        self.pools = Pools(
            pool_filter=lambda p:
            p.quote_token.is_native_currency() and
            p.liquidity > 3000 and
            p.volume > 5000,
            repeated_pool_filter_key=lambda p:
            p.volume,
        )
        self.growing_pools_cached = None
        self.users: Users = Users()
        self.geckoterminal_api = GeckoTerminalAPIWrapper(max_requests=settings.GECKO_TERMINAL_MAX_REQUESTS_PER_CYCLE)
        self.ton_api = AsyncTonapi(api_key=os.environ.get('TON_API_KEY'))

        self.application = ApplicationBuilder().token(os.environ.get('TELEGRAM_BOT_TOKEN')).build()
        self.bot: Bot = self.application.bot

        self.application.add_handler(CommandHandler('help', self.help))
        self.application.add_handler(CommandHandler('resend', self.resend))
        self.application.add_handler(CommandHandler('follow', self.follow))
        self.application.add_handler(CommandHandler('unfollow', self.unfollow))

    def run(self):
        asyncio.run(self.run_event_loop())

    async def run_event_loop(self):
        await self.bot.set_my_commands([
            ('/help', settings.COMMAND_HELP_DESCRIPTION),
            ('/resend', settings.COMMAND_RESEND_DESCRIPTION),
        ])

        async with self.application:
            await self.application.start()
            await self.application.updater.start_polling()

            try:
                while True:
                    await self.run_one_cycle()
            except CancelledError as e:
                logger.info(f'Stopping the bot because of an exit signal{" - " + str(e) if str(e) else str(e)}')

            await self.application.updater.stop()
            await self.application.stop()

    async def run_one_cycle(self):
        start_time = time.time()

        logger.info('Updating pools')
        self.pools.clear()
        await self.geckoterminal_api.update_pools(self.pools)
        logger.info(f'Pools/Tokens: {len(self.pools)}/{len(self.pools.get_tokens())}')

        def growth_score(p: Pool):
            return 3 * max(p.price_change.m5 * 100, 0) + max(p.price_change.h1 * 100, 0)

        growing_pools = [p for p in self.pools if growth_score(p) > 5]
        growing_pools.sort(key=growth_score, reverse=True)
        logger.info(f'Updating pinned messages - Growing pools: {len(growing_pools)}')
        await self.update_pinned_message(growing_pools)

        pumped_pools = [p for p in growing_pools if growth_score(p) > 25]
        growing_pools.sort(key=growth_score, reverse=True)
        logger.info(f'Sending notifications (if there are) - Pumped pools: {len(pumped_pools)}')
        await self.send_notifications(pumped_pools)

        cooldown = settings.UPDATES_COOLDOWN - (time.time() - start_time)
        if cooldown > 0:
            logger.info(f'Going to asynchronous sleep - {cooldown:.0f}s')
            await asyncio.sleep(cooldown)

    async def update_pinned_message(self, growing_pools):
        self.growing_pools_cached = growing_pools

        for user in self.users.get_users():
            followlist = self.users.get_followlist(user, self.pools)

            message = pools_to_message(
                [self.pools.find_best_token_pool(t, key=lambda p: p.volume) for t in followlist if self.pools.has_token(t)],
                prefix='Followlist',
                age=True,
                fdv=True,
                volume=True,
                liquidity=True,
                transactions=True,
                makers=True,
                price_change=True,
                buyers_sellers_change=True
            )
            message = pools_to_message(
                [p for p in growing_pools if p.base_token not in followlist],
                prefix='Growing pools',
                postfix=('', datetime.now().strftime('%d.%m.%Y, %H:%M:%S')),
                message_before=message,
                age=True,
                fdv=True,
                volume=True,
                liquidity=True,
                transactions=True,
                makers=True,
                price_change=True,
                buyers_sellers_change=True
            )

            if message:
                if not self.users.has_pinned_message_id(user):

                    if message := await self.send_message(message, user):
                        if await self.unpin_all_messages(user):

                            if await self.pin_message(user, message.message_id):
                                self.users.set_pinned_message_id(user, message.message_id)
                            else:
                                logger.warning(f'Can\'t pin the message - {user.id}/{message.message_id}')
                        else:
                            logger.warning(f'Can\'t unpin all chat messages - {user.id}')

                elif not await self.edit_message(message, user, self.users.get_pinned_message_id(user)):
                    logger.info(f'Can\'t edit the pinned message - {user.id}/{self.users.get_pinned_message_id(user)}')
                    self.users.remove_pinned_message_id(user)

    async def send_notifications(self, pumped_pools):
        async def get_jetton_balances(user: User) -> list[JettonBalance] | None:
            try:
                return (await self.ton_api.accounts.get_jettons_balances(user.wallet)).balances

            except AttributeError as e:
                logger.warning(f'Getting jetton balances via TON API: {str(e)} - {user.id}')
                return None

        for user in self.users.get_users():
            data = []

            if jetton_balances := await get_jetton_balances(user):
                for x in jetton_balances:
                    balance = int(x.balance)
                    token = self.pools.get_token(x.jetton.address.to_userfriendly(is_bounceable=True))
                    token_balance = user.get_token_balance(token)

                    if balance:
                        if pool := self.pools.find_best_token_pool(token, key=lambda p: p.volume):

                            if not token_balance:
                                token.update(decimals=x.jetton.decimals)  # update info about token itself
                            else:
                                change = 1 - pool.price_in_native_currency / token_balance.rate
                                notification = user.get_last_token_notification(token)

                                if (
                                        abs(change) > settings.NOTIFICATIONS_USER_WALLET_CHANGE_BOUND and
                                        (not notification.has_been_made() or notification.seconds_passed() > settings.NOTIFICATIONS_PUMP_COOLDOWN)
                                ):
                                    notification.make()
                                    data.append((pool, change))

                            user.update_token_balance(token, amount=balance, rate=pool.price_in_native_currency)
                    elif token_balance:
                        user.remove_token_balance(token_balance)

            data.sort(key=lambda x: x[1], reverse=True)
            data = list(zip(*data))
            wallet_pools_user, change = (data[0], data[1]) if data else ([], [])
            pumped_pools_user = []

            for pool in pumped_pools:
                notification = user.get_last_token_notification(pool.base_token)

                if not pool in wallet_pools_user:
                    if not notification.has_been_made() or notification.seconds_passed() > settings.NOTIFICATIONS_PUMP_COOLDOWN:
                        notification.make()
                        pumped_pools_user.append(pool)

            tickers = [p.base_token.ticker for p in [*pumped_pools_user, *wallet_pools_user]]
            name = (', '.join(tickers), '') if len(tickers) > 1 else ''

            message = pools_to_message(
                wallet_pools_user,
                prefix=name,
                balance=[user.get_token_balance(p.base_token).calculate_balance() for p in wallet_pools_user],
                change=change,
                age=True,
                fdv=True,
                volume=True,
                liquidity=True,
                transactions=True,
                makers=True,
                price_change=True,
                buyers_sellers_change=True
            )

            message = pools_to_message(
                pumped_pools_user,
                prefix=name if not wallet_pools_user else '',
                message_before=message,
                age=True,
                fdv=True,
                volume=True,
                liquidity=True,
                transactions=True,
                makers=True,
                price_change=True,
                buyers_sellers_change=True
            )

            if message:
                await self.send_message(message, user)

    async def send_message(self, text, user: User) -> Message | None:
        prefix = 'Sending message: '

        try:
            return await self.bot.send_message(user.id, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

        except error.Forbidden as e:
            logger.info(f'{prefix}{e} - {user.id}')

        except error.BadRequest as e:
            if str(e) == settings.BAD_REQUEST_MESSAGE_IS_TOO_LONG:
                logger.error(f'{prefix}{e} - {len(clear_from_html(text))} chars - {user.id}')

        except error.TimedOut as e:
            logging.warning(f'{prefix}{e} - {user.id}')

        return None

    async def edit_message(self, text, user: User, message_id) -> bool:
        prefix = 'Editing message: '

        try:
            return await self.bot.edit_message_text(text, user.id, message_id, parse_mode=ParseMode.HTML, disable_web_page_preview=True) is not True

        except error.Forbidden as e:
            logger.info(f'{prefix}{e} - {user.id}')

        except error.BadRequest as e:
            if str(e) ==  settings.BAD_REQUEST_MESSAGE_IS_NOT_MODIFIED:
                logger.warning(f'{prefix}{e} - {user.id}/{message_id}')
            elif str(e) == settings.BAD_REQUEST_MESSAGE_IS_TOO_LONG:
                logger.error(f'{prefix}{e} - {len(clear_from_html(text))} chars - {user.id}/{message_id}')

        except error.TimedOut as e:
            logging.warning(f'{prefix}{e} - {user.id}/{message_id}')

        return False

    async def pin_message(self, user: User, message_id) -> bool:
        return await self.bot.pin_chat_message(user.id, message_id, disable_notification=True)

    async def unpin_all_messages(self, user: User) -> bool:
        return await self.bot.unpin_all_chat_messages(user.id)

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(settings.COMMAND_HELP_MESSAGE, parse_mode=ParseMode.HTML)

    async def resend(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.users.remove_pinned_message_id(self.users.get_user(update.message.chat_id))
        await self.update_pinned_message(self.growing_pools_cached)

    async def follow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.message.chat_id

        if (result := await self._extract_symbol_and_tokens(update)) is not None:
            symbol, matches = result

            if len(matches) == 1:
                self.users.add_to_followlist(self.users.get_user(user_id), matches[0])
                await update.message.reply_text(f'{matches[0].ticker} was added to the followlist')
            elif len(matches) > 1:
                logger.info(f'/follow: Multiple tokens with symbol {symbol} - {user_id}')
                await update.message.reply_text(f'There are multiple tokens with this symbol, symbol is ambiguous')
            else:
                logger.info(f'/follow: Unknown symbol {symbol} - {user_id}')
                await update.message.reply_text(f'Unknown symbol')

    async def unfollow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.message.chat_id

        if (result := await self._extract_symbol_and_tokens(update)) is not None:
            symbol, matches = result

            if len(matches) == 1:
                self.users.remove_from_followlist(self.users.get_user(user_id), matches[0])
                await update.message.reply_text(f'{matches[0].ticker} was removed from the followlist')
            else:
                logger.info(f'Unknown symbol or there are multiple tokens with symbol {symbol} - {user_id}')
                await update.message.reply_text(f'Unknown symbol or there are multiple tokens with such symbol')

    async def _extract_symbol_and_tokens(self, update: Update) -> tuple[str, list[Token]] | None:
        try:
            symbol = update.message.text.split(' ', 1)[1].strip()
            return symbol, [t for t in self.pools.get_tokens() if t.ticker.lower() == symbol.lower()]
        except Exception as e:
            logger.info(f'/follow: Invalid argument: {update.message.text} - {e}')
            await update.message.reply_text(f'Invalid argument')
            return None


if __name__ == '__main__':
    DEXScanner().run()
