import asyncio
import logging
import os
import time
from asyncio import CancelledError

from pytonapi import AsyncTonapi
from telegram import error, Bot, Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler

import constants
import settings
from gecko_terminal_api_wrapper import GeckoTerminalAPIWrapper
from pools import Pools, Pool, Token
from utils import format_number, round_to_significant_figures

logging.basicConfig(
    format=settings.LOGGING_FORMAT,
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # set higher logging level for httpx to avoid all GET and POST requests being logged
logger = logging.getLogger(__name__)

Id = int


def get_text_len_without_html(text):
    tags = ['<code>']
    tags = [*tags, *['</' + t[1:] for t in tags]]
    tags_len = 0

    for tag in tags:
        counts = text.count(tag)
        tags_len += counts * len(tag)

    return len(text) - tags_len


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
        self.amount = amount
        self.rate = rate

    def calculate_balance(self):
        return self.amount * 10 ** -self.token.decimals * self.rate


class PinnedMessage:
    def __init__(self, id, text):
        self.id = id
        self.text = text


class User:
    def __init__(self, id, wallet):
        self.id = id
        self.pinned_message: PinnedMessage or None = None
        self.wallet = wallet
        self.token_balances: dict[Token, TokenBalance] = {}
        self.followlist = []

    def update_token_balance(self, token: Token, **data):
        if token not in self.token_balances:
            self.token_balances[token] = TokenBalance(token, **data)
        else:
            self.token_balances[token].update(**data)

    def get_token_balance(self, token: Token) -> TokenBalance | None:
        if token in self.token_balances:
            return self.token_balances[token]
        return None


class DEXScanner:
    def __init__(self):
        self.application = ApplicationBuilder().token(os.environ.get('TELEGRAM_BOT_TOKEN')).build()
        self.bot: Bot = self.application.bot
        self.ton_api = AsyncTonapi(api_key=os.environ.get('TON_API_KEY'))
        self.geckoterminal_api = GeckoTerminalAPIWrapper(max_requests=settings.GECKO_TERMINAL_MAX_REQUESTS_PER_CYCLE)
        self.pools = Pools()
        self.users: dict[Id, User] = {}

    async def follow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        symbol = None
        try:
            symbol = update.message.text.split(' ', 1)[1].strip()
        except Exception as e:
            logger.info(f'Chat ID: {str(id)} - Invalid command: {update.message.text} - {str(e)}')
            await update.message.reply_text(f'Invalid command: {update.message.text}!')

        matches = [t for t in self.pools.get_tokens() if t.symbol.lower() == symbol.lower()]
        if len(matches) == 1:
            self.users[update.message.chat_id].followlist.append(matches[0])
            await update.message.reply_text(f'Token {matches[0].symbol} was successfully added to the followlist')
        elif not matches:
            logger.info(f'Chat ID: {str(id)} - Unknown token symbol: {symbol}')
            await update.message.reply_text(f'Sorry, bot doesn\'t have this token')
        else:
            logger.info(f'Chat ID: {str(id)} - There are multiple tokens with symbol: {symbol}!')
            await update.message.reply_text(f'There are multiple tokens with symbol. Symbol is ambiguous')

    async def unfollow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        symbol = None
        try:
            symbol = update.message.text.split(' ', 1)[1].strip()
        except Exception as e:
            logger.info(f'Chat ID: {str(id)} - Invalid command: {update.message.text} - {str(e)}')
            await update.message.reply_text(f'Invalid command: {update.message.text}!')

        matches = [t for t in self.users[update.message.chat_id].followlist if t.symbol.lower() == symbol.lower()]
        if len(matches) == 1:
            self.users[update.message.chat_id].followlist.remove(matches[0])
            await update.message.reply_text(f'Token {matches[0].symbol} was successfully removed from the followlist')
        else:
            logger.info(f'Chat ID: {str(id)} - Unknown token symbol: {symbol}')
            await update.message.reply_text(f'Sorry, bot doesn\'t have this token in the followlist')

    def run(self):
        asyncio.run(self.run_event_loop())

    async def run_event_loop(self):
        self.application.add_handler(CommandHandler('follow', self.follow))
        self.application.add_handler(CommandHandler('unfollow', self.unfollow))

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
        logger.info('Updating pools')
        start_time = time.time()
        self.geckoterminal_api.update_pools(self.pools)
        self.pools.filter_repeated_pools(lambda p: p.volume, reverse=True)
        selected_pools = self.pools.select_pools(
            lambda p:
            p.liquidity > 5000 and
            p.price_change.m1 > 0.01 and
            p.price_change.h24 > 0.03
        )
        selected_pools.sort(key=lambda p: p.price_change.m5, reverse=True)

        logger.info(f'Updating pinned message (total pools: {len(self.pools)}, selected pools: {len(selected_pools)})')
        for user in self.users.values():
            message = None
            followlist = self.users[user.id].followlist

            if followlist:
                message = '<code>Following pools</code>'

                for token in followlist:
                    append = '\n\n' + self.create_pool_message(self.pools.find_best_token_pool(token))
                    if get_text_len_without_html(message + append) > constants.TELEGRAM_MESSAGE_MAX_LEN:
                        break
                    message += append

            if selected_pools:
                local_message = '<code>Growing pools</code>'
                at_least_one_pool = False

                for pool in selected_pools:
                    if pool.base_token not in followlist:
                        append = '\n\n' + self.create_pool_message(pool)
                        if get_text_len_without_html((message if message else '') + local_message + append) > constants.TELEGRAM_MESSAGE_MAX_LEN:
                            break
                        local_message += append
                        at_least_one_pool = True

                if at_least_one_pool:
                    message = message + '\n\n' + local_message if message else local_message

            if message:
                if not user.pinned_message:
                    await self.send_message(user, message, pinned_message=True)
                else:
                    await self.update_message(user, message, pinned_message=True)
                logger.info(f'Updated the message ({user.id}/{user.pinned_message.id})')

        logger.info(f'Sending alerts (if needed)')
        for user in self.users.values():
            data = []

            for x in (await self.ton_api.accounts.get_jettons_balances(user.wallet)).balances:

                if int(x.balance) and (token := self.pools.get_token(x.jetton.address.to_userfriendly(is_bounceable=True))):
                    if pool := self.pools.find_best_token_pool(token):

                        if not (token_balance := user.get_token_balance(token)):
                            token.update(decimals=x.jetton.decimals)
                            user.update_token_balance(token, amount=int(x.balance), rate=pool.price_in_native_currency)
                        else:
                            change = 1 - pool.price_in_native_currency / token_balance.rate
                            timestamp = token_balance.timestamp

                            if abs(change) > settings.ALERTS_CHANGE_BOUND and (not timestamp.has_been_made() or timestamp.seconds_passed() > settings.ALERTS_COOLDOWN):
                                timestamp.make()
                                token_balance.rate = pool.price_in_native_currency
                                data.append((pool, change))

            if data:
                data.sort(key=lambda x: x[1], reverse=True)
                message = '<code>Alert!</code>'

                for pool, change in data:
                    append = '\n\n' + self.create_pool_message(pool, alert=(change, user.get_token_balance(pool.base_token).calculate_balance()))
                    if get_text_len_without_html(message + append) > constants.TELEGRAM_MESSAGE_MAX_LEN:
                        break
                    message += append

                await self.send_message(user, message)

        logger.info(f'Taking cooldown')
        cooldown = settings.UPDATES_COOLDOWN - (time.time() - start_time)
        if cooldown > 0:
            await asyncio.sleep(cooldown)

    @staticmethod
    def create_pool_message(pool: Pool, alert: tuple[float, float] = None):
        line_width = 36  # 34-36
        lines = []

        def add_line(s1, s2):
            lines.append(f'{s1}{" " * (line_width - (len(s1) + len(s2)))}{s2}')

        add_line(
            pool.base_token.symbol if pool.quote_token.is_native_currency() else pool.base_token.symbol + '/' + pool.quote_token.symbol,
            format_number(pool.price, 4, 9, symbol='$', significant_figures=2)
        )

        if alert:
            add_line('Balance:', f'{round_to_significant_figures(alert[1], 3)} {settings.NETWORK.upper()}')
            add_line('Change:', format_number(alert[0], 4, sign=True, percent=True, significant_figures=2))

        if not alert:
            add_line('FDV:', format_number(pool.fdv, 6, symbol='$', k_mode=True))
            add_line('Volume:', format_number(pool.volume, 6, symbol='$', k_mode=True))
            add_line('Liquidity:', format_number(pool.liquidity, 6, symbol='$', k_mode=True))
            add_line('Transactions:', str(round_to_significant_figures(pool.transactions, 2)))
            add_line('Makers:', str(round_to_significant_figures(pool.makers, 2)))
            add_line('TXs/wallet', str(round_to_significant_figures(pool.transactions_per_wallet, 2)))

        for name, td in [('Price:', pool.price_change), ('Buy/sell:', pool.buy_sell_change), ('Buyers/sellers:', pool.buyers_sellers_change)]:
            m5 = format_number(td.m5, 3, sign=True, percent=True, significant_figures=2)
            h1 = format_number(td.h1, 4, sign=True, percent=True, significant_figures=2)
            h24 = format_number(td.h24, 4, sign=True, percent=True, significant_figures=2)
            percents = f'{m5} {h1} {h24}'
            add_line(name, percents)

        links_between_width = line_width - 22
        links = f'<a href="https://www.geckoterminal.com/{settings.NETWORK}/pools/{pool.address}">GeckoTerminal</a>'

        if pool.dex.id == 'dedust':
            links = '<code>' + ' ' * links_between_width + '</code>' + links
            links = f'<a href="https://dexscreener.com/{settings.NETWORK}/{pool.address}">DEX Screener</a>' + links
        else:
            links = ' ' + '<code>' + ' ' * (10 + (line_width - 22)) + '</code>' + links

        return '<code>' + '\n'.join(lines) + '</code>' + '\n' + links

    async def send_message(self, user: User, text, pinned_message=False):
        try:
            message = await self.bot.send_message(user.id, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

            if pinned_message:
                if not await self.bot.unpin_all_chat_messages(user.id):
                    logger.info(f'Can\'t unpin all chat messages! ({str(id)}/{message.message_id})')
                if not await self.bot.pin_chat_message(user.id, message.message_id, disable_notification=True):
                    logger.info(f'Can\'t pin the message! ({str(id)}/{message.message_id})')
                user.pinned_message = PinnedMessage(message.message_id, text)

        except error.Forbidden as e:
            logger.info(f'{str(id)} - {str(e)}')
            user.pinned_message = None

    async def update_message(self, user: User, text, pinned_message=False):
        if text != user.pinned_message.text:
            message = await self.bot.edit_message_text(text, user.id, user.pinned_message.id, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

            if message is not True:
                if pinned_message:
                    user.pinned_message.text = text
            else:
                logger.info(f'Can\'t edit the message! ({str(id)}/{message.message_id})')
                user.pinned_message = None


if __name__ == '__main__':
    DEXScanner().run()
