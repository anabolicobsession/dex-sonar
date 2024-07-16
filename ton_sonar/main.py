import asyncio
from os import environ
from collections.abc import Iterable
import logging
from asyncio import CancelledError
from datetime import timedelta
from io import BytesIO

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CallbackQueryHandler
from aiogram import html

from ton_sonar.bot import Bot
from ton_sonar.config.config import config, pool_filter, TESTING_MODE, NETWORK
from ton_sonar.logs import setup_logging
from ton_sonar.network.pools_with_api import PoolsWithAPI
from ton_sonar.network.pool_with_chart import Pool, TrendsView, PlotSizeScheme, SizeScheme, OpacityScheme, MaxBinsScheme
from ton_sonar.network.network import Token
from ton_sonar.users import Users
from ton_sonar.utils.utils import format_number, difference_to_pretty_str


setup_logging()
logger = logging.getLogger(__name__)


def pools_to_message(
        pools: Iterable[Pool],
        pattern_message: str,
        prefix: str | tuple[str, str] | None = None,
        postfix: str | tuple[str, str] | None = None,
        line_width=35,
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

    def add_line(str1, str2=None):
        if str2 is None:
            lines.append(str1)
            return
        lines.append(f'{str1}{spaces(line_width - (len(str1) + len(str2)))}{str2}')

    for i, pool in enumerate(pools):
        lines = []

        add_line(
            (pool.base_token.ticker if pool.quote_token.is_native_currency() else pool.base_token.ticker + '/' + pool.quote_token.ticker),
            pattern_message,
        )

        if pool.liquidity: add_line('Liquidity:', format_number(pool.liquidity, 6, symbol='$', k_mode=True))
        add_line('Volume:', format_number(pool.volume, 6, symbol='$', k_mode=True))
        if pool.creation_date: add_line('Age:', difference_to_pretty_str(pool.creation_date))

        add_line(
            'Price:',
            format_number(pool.price_native, 1, 9, significant_figures=2) + ' ' + NETWORK.name + ' ' +
            format_number(pool.price_usd, 4, 9, symbol='$', significant_figures=2),
        )

        geckoterminal = html.link('GeckoTerminal', f'https://www.geckoterminal.com/{NETWORK.get_id()}/pools/{pool.address}')
        dex_screener = html.link('DEX Screener', f'https://dexscreener.com/{NETWORK.get_id()}/{pool.address}')
        links = geckoterminal + html.code(spaces(line_width - 22)) + dex_screener

        pool_message = get_updated_message_pools(html.code('\n'.join(lines)) + '\n' + links + '\n' + html.code(pool.base_token.address))

    return get_full_message(pool_message)


class Application:
    def __init__(self):
        self.bot = Bot(
            token=environ.get('BOT_TOKEN') if not TESTING_MODE else environ.get('TESTING_BOT_TOKEN'),
            token_silent=environ.get('SILENT_BOT_TOKEN') if not TESTING_MODE else environ.get('TESTING_SILENT_BOT_TOKEN'),
        )

        self.pools = PoolsWithAPI(
            pool_filter=pool_filter,
            repeated_pool_filter_key=lambda x: x.volume,
        )
        self.users: Users = Users()
        self.cooldown = config.getfloat('Pools', 'update_cooldown')

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
        self.bot.run(self.run_main_loop())

    async def run_main_loop(self):
        try:
            await self.bot.set_description('Live')
            while True: await self.run_cycle()

        except CancelledError:
            logger.info(f'Stopping the bot')

        finally:
            await self.bot.set_description(None)
            await self.pools.close_api_sessions()
            self.users.close_connection()

    async def run_cycle(self):
        logger.info('Updating pools')
        await self.pools.update_using_api()
        logger.info(f'Pools: {len(self.pools)}')

        await self.send_messages_if_patterns_detected()

        logger.info(f'Sleep for {self.cooldown:.0f}s\n')
        await asyncio.sleep(self.cooldown)

    async def send_messages_if_patterns_detected(self):
        logger.info(f'Checking for patterns')
        tuples = []

        for pool in self.pools:
            if match := pool.chart.get_pattern(only_new=True):
                with (
                    pool.chart.create_plot(
                        trends_view=TrendsView.GLOBAL,
                        price_in_percents=True,

                        plot_size_scheme=PlotSizeScheme(
                            width=8,
                            ratio=0.5,
                        ),
                        datetime_format='%H:%M',

                        size_scheme=SizeScheme(
                            tick=15,
                        ),
                        opacity_scheme=OpacityScheme(
                            # volume=0.4,
                        ),
                        max_bins_scheme=MaxBinsScheme(
                            x=5,
                            y=5,
                        )
                ) as (_, fig, _, _)):

                    plot_buffer = BytesIO()
                    fig.savefig(
                        plot_buffer,
                        format='png',
                        dpi=400,
                        bbox_inches='tight',
                        pad_inches=0.3,
                    )
                    tuples.append((pool, match, plot_buffer))


        if tuples:
            tuples.sort(key=lambda x: x[1].magnitude, reverse=True)
            logger.info(f'Pools with patterns: {len(tuples)}')
        else:
            logger.info('No patterns found')
            return

        for user_id in self.users.get_user_ids():

            for pool, match, plot_buffer in tuples:

                if not self.users.is_muted(user_id, pool.base_token):

                    pattern_message = match.pattern.get_name() + f' {match.magnitude:.0%}'
                    await self.bot.send_message(
                        user_id,
                        pools_to_message([pool], pattern_message),
                        plot_buffer,
                        reply_markup=self.reply_markup_mute,
                        silent=not match.significant
                    )

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
                self.users.mute_for(user_id, token, timedelta(days=option))
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
