import asyncio
import os
from collections.abc import Iterable
import logging
import time
from asyncio import CancelledError
from datetime import timedelta, datetime
from enum import Enum, auto
from io import BytesIO

from telegram import error, Bot, Update, Message, LinkPreviewOptions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, Defaults, CallbackQueryHandler
from aiogram import html

import network
import settings
from pools_with_api import PoolsWithAPI
from extended_pool import Pool
from users import UserId, Users
from utils import format_number, clear_from_html, difference_to_pretty_str

root_logger = logging.getLogger()
root_logger.setLevel(level=settings.LOGGING_LEVEL)
logger = logging.getLogger(__name__)
logging_formatter = logging.Formatter(settings.LOGGING_FORMAT)

handler = logging.StreamHandler()
handler.setLevel(settings.LOGGING_LEVEL)
handler.setFormatter(logging_formatter)
root_logger.addHandler(handler)

logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.INFO)
logging.getLogger('matplotlib').setLevel(logging.INFO)
logging.getLogger('telegram').setLevel(logging.INFO)


MessageID = int


class ImpossibleAction(Exception):
    ...


class UnknownException(Exception):
    ...


class Status(Enum):
    SUCCESS = auto()
    REMOVED = auto()
    BLOCK = auto()
    EXCEPTION = auto()


def pools_to_message(
        pools: Iterable[Pool],
        signal: str,
        prefix: str | tuple[str, str] | None = None,
        postfix: str | tuple[str, str] | None = None,
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
            signal,
        )

        left = 3

        # m5 = format_number(pool.price_change.m5, left, sign=True, percent=True, significant_figures=2)
        # h1 = format_number(pool.price_change.h1, left, sign=True, percent=True, significant_figures=2)
        # h6 = format_number(pool.price_change.h6, left, sign=True, percent=True, significant_figures=2)
        # add_line('Price:', f'{m5} {h1} {h6}')

        # for name, timedata in [('Buyers/Sellers:', pool.buyers_sellers_ratio), ('Volume ratio:', pool.volume_ratio)]:
        #     m5 = format_number(round(timedata.m5, 1),  left, 1)
        #     h1 = format_number(round(timedata.h1, 1), left, 1)
        #     h6 = format_number(round(timedata.h6 if name != 'Buyers/Sellers:' else timedata.h24, 1),  left, 1)
        #     add_line(name, f'{m5} {h1} {h6}')

        if pool.liquidity: add_line('Liquidity:', format_number(pool.liquidity, 6, symbol='$', k_mode=True))
        add_line('Volume:', format_number(pool.volume, 6, symbol='$', k_mode=True))
        # add_line('Makers:', str(round_to_significant_figures(pool.makers, 2)))
        # add_line('TXNs/Makers:', format_number(round(pool.transactions / pool.makers, 1), 3, 1))
        if pool.creation_date: add_line('Age:', difference_to_pretty_str(pool.creation_date))

        add_line(
            'Price:',
            format_number(pool.price_usd, 4, 6, symbol='$', significant_figures=2),
        )

        add_line(
            'Price:',
            format_number(pool.price_native, 4, 6, symbol=settings.NETWORK.name + ' ', significant_figures=2),
        )

        geckoterminal = html.link('GeckoTerminal', f'https://www.geckoterminal.com/{settings.NETWORK.get_id()}/pools/{pool.address}')
        swap_coffee = html.link('swap.coffee', f'https://swap.coffee/dex?ft=TON&st={pool.base_token.ticker}')
        dex_screener = html.link('DEX Screener', f'https://dexscreener.com/{settings.NETWORK.get_id()}/{pool.address}')
        links = geckoterminal + html.code(spaces(line_width - 33)) + swap_coffee + html.code(spaces(1)) + ' ' + dex_screener

        new_pool_message = get_updated_message_pools(html.code('\n'.join(lines)) + '\n' + links + '\n' + html.code(pool.base_token.address))

        if len(clear_from_html(get_full_message(new_pool_message))) <= message_max_length:
            pool_message = new_pool_message
        else:
            break

    return get_full_message(pool_message)


class TONSonar:
    def __init__(self):
        self.bot: Bot | None = None
        self.pools = PoolsWithAPI(
            pool_filter=settings.POOL_DEFAULT_FILTER,
            repeated_pool_filter_key=lambda x: x.volume,
        )
        self.users: Users = Users()

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
        application = ApplicationBuilder().token(os.environ.get('TELEGRAM_BOT_TOKEN' if settings.PRODUCTION_BOT else 'TELEGRAM_BOT_TOKEN_DEVELOPMENT')).defaults(defaults).build()
        application.add_handler(CallbackQueryHandler(self.buttons_mute))
        self.bot = application.bot

        async with application:
            await application.start()
            await application.updater.start_polling()

            try:
                while True:
                    await self.run_one_cycle()
            except CancelledError as e:
                logger.info(f'Stopping the bot{" - " + str(e) if str(e) else str(e)}')
                await self.safely_end_all_processes()
            except Exception as e:
                await self.pools.close_api_sessions()
                raise e

            await application.updater.stop()
            await application.stop()

    async def safely_end_all_processes(self):
        self.users.close_connection()
        await self.pools.close_api_sessions()

    async def run_one_cycle(self):
        start_time = time.time()

        logger.debug('Updating pools')
        await self.pools.update_using_api()
        logger.info(f'Pools: {len([x for x in self.pools])}')

        await self.send_signal_messages()
        await self.bot.set_my_short_description(f'Last update: {datetime.now().strftime("%I:%M %p")}')

        logger.debug(f'Going to asynchronous sleep - {settings.UPDATES_COOLDOWN:.0f}s')
        logger.debug('\n')
        await asyncio.sleep(settings.UPDATES_COOLDOWN)

    async def send_signal_messages(self):
        logger.debug(f'Checking for signals')
        tuples = []

        for p in self.pools:
            if x := p.chart.get_signal(p, only_new=True):
                figure = p.chart.create_plot(
                    width=8,
                    ratio=0.6,

                    percent=True,
                    tick_limit=1500,
                    datetime_format='%H:%M',

                    volume_opacity=0.4,

                    tick_size=15,
                    xtick_bins=5,
                    ytick_bins=5,
                )

                buffer = BytesIO()
                figure.savefig(
                    buffer,
                    format='png',
                    dpi=200,
                    bbox_inches='tight',
                    pad_inches=0.3,
                )
                buffer.seek(0)

                tuples.append((p, *x, buffer))

        if not tuples:
            return
        tuples.sort(key=lambda x: x[2], reverse=True)

        logger.info(f'Signals: {len(tuples)}')

        for user_id in self.users.get_user_ids():
            for pool, signal, magnitude, buffer in tuples:

                if not self.users.is_muted(user_id, pool.base_token):
                    # self.users.mute_for(user_id, pool.base_token, settings.NOTIFICATION_PUMP_COOLDOWN)
                    # _, status = await self.send_message(message, user_id, reply_markup=self.reply_markup_mute)

                    message = pools_to_message([pool], repr(signal) + f' {magnitude * 100:.0f}%')

                    buffer.seek(0)

                    try:
                        await self.bot.send_photo(user_id, buffer, message, reply_markup=self.reply_markup_mute)
                    except Exception as e:
                        logger.warning(f'During sending message: {e}')

                    # if status is Status.BLOCK:
                    #     break

    async def send_message(self, text, users_id: UserId, **kwargs) -> tuple[Message | None, Status]:
        def to_info(str, append=None):
            return f'{str} - Chat ID: {users_id}' + (f' - {append}' if append else '')

        try:
            return await self.bot.send_message(users_id, text, **kwargs), Status.SUCCESS

        except error.Forbidden as e:
            if str(e) == settings.TELEGRAM_FORBIDDEN_BLOCK:
                logger.info(to_info(f'User blocked the bot'))
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

        await query.answer()

        if not token:
            await self.send_message('Sorry, unable to do this action in the current program version', user_id, disable_notification=True)
            return

        if option:
            if option > 0:
                self.users.mute_for(user_id, token, timedelta(days=option))
            else:
                self.users.mute_forever(user_id, token)

            duration = f'for {option} day{"" if option == 1 else "s"}' if option > 0 else 'forever'
            await query.edit_message_caption(caption=f'Successfully muted {token.ticker} {duration}', reply_markup=self.reply_markup_unmute)
        else:
            self.users.unmute(user_id, token)
            await query.edit_message_caption(caption=   f'{token.ticker} was unmuted')


if __name__ == '__main__':
    TONSonar().run()
