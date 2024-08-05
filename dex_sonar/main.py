import gc
import logging
from asyncio import CancelledError
from io import BytesIO
from os import environ

from aiogram import html
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import NetworkError
from telegram.ext import CallbackQueryHandler, ContextTypes

from dex_sonar.bot import Bot
from dex_sonar.config.config import TESTING_MODE, USER_TIMEZONE, config
from dex_sonar.logs import setup_logging
from dex_sonar.network_and_pools.network import Network, Token
from dex_sonar.network_and_pools.pool_with_chart import Backend, MaxBinsScheme, PlotSizeScheme, Pool, SizeScheme, TrendsView
from dex_sonar.network_and_pools.pools_with_api import PoolsWithAPI
from dex_sonar.users import Users
from dex_sonar.utils.time import Cooldown, Timedelta
from dex_sonar.utils.utils import format_number


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
            callback_coroutine=self.send_messages_if_patterns_detected,

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
                cooldown=Timedelta(seconds=0.9375),  # 60 / 64 (binary powers of minute)
                multiplier=2,
                within_time_period=Timedelta(minutes=20),
            ),
        )
        self.users: Users = Users()

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
            await self.bot.set_description('Live')
            while True: await self.pools.update_via_api()

        except CancelledError:
            logger.info(f'Stopping the bot')

        except NetworkError as e:
            logger.error(f'Caught telegram network error: {e}')

        finally:
            await self.bot.set_description(None)
            await self.pools.close_api_sessions()
            self.users.close_connection()

    async def send_messages_if_patterns_detected(self):
        tuples = []

        for pool in self.pools:
            if match := pool.chart.get_pattern(only_new=True):
                with (
                    pool.chart.create_plot(
                        trends_view=TrendsView.GLOBAL,
                        price_in_percents=True,
                        backend=Backend.AGG,

                        plot_size_scheme=PlotSizeScheme(
                            width=8,
                            ratio=0.5,
                        ),
                        datetime_format='%H:%M',
                        specific_timezone=USER_TIMEZONE,

                        size_scheme=SizeScheme(
                            tick=15,
                        ),
                        max_bins_scheme=MaxBinsScheme(
                            x=5,
                            y=5,
                        )
                ) as (plt, fig, _, _)):

                    plot_buffer = BytesIO()
                    fig.savefig(
                        plot_buffer,
                        format='png',
                        dpi=150,
                        bbox_inches='tight',
                        pad_inches=0.3,
                    )
                    tuples.append((pool, match, plot_buffer))

                    plt.close(fig)
                    plt.cla()
                    plt.clf()
                    plt.close('all')
                    gc.collect()

        if tuples:
            tuples.sort(key=lambda x: x[1].magnitude, reverse=True)
            tickers = [x[0].base_token.ticker for x in tuples]
            logger.info(f'Detected pools with patterns: {", ".join(tickers)} - Sending messages (if a token is not muted)')
        else:
            return

        for user_id in self.users.get_user_ids():

            for pool, match, plot_buffer in tuples:

                if not self.users.is_muted(user_id, pool.base_token):

                    pattern_message = match.pattern.get_name() + f' {match.magnitude:.0%}'

                    await self.bot.send_message(
                        user_id,
                        self.pool_to_message(pool, pattern_message),
                        plot_buffer,
                        reply_markup=self.reply_markup_mute,
                        silent=not match.significant
                    )

                    plot_buffer.close()
                    gc.collect()

    @staticmethod
    def pool_to_message(pool: Pool, append: str, width: int = config.getint('Message', 'width')):
        lines = []

        def add_line(a: str, b: str):
            chars_left = width - len(a) - len(b)
            lines.append(f'{a}{" " * chars_left}{b}')

        add_line(pool.get_shortened_name() if pool.has_native_quote_token() else pool.get_name(), append)
        add_line('FDV:', format_number(pool.fdv, 6, symbol='$', k_mode=True))
        add_line('Volume:', format_number(pool.volume, 6, symbol='$', k_mode=True))
        add_line('Liquidity:', format_number(pool.liquidity, 6, symbol='$', k_mode=True))
        add_line('Age:', pool.creation_date.time_elapsed().to_human_readable_format())
        add_line('Price:', format_number(pool.price_usd, 4, 9, symbol='$', significant_figures=2))

        network = pool.network.get_id()
        address = pool.address
        ticker = pool.base_token.ticker

        geckoterminal = html.link('GeckoTerminal', f'https://www.geckoterminal.com/{network}/pools/{address}')
        dextools = html.link('DEXTools', f'https://www.dextools.io/app/en/{network}/pair-explorer/{address}')
        dex_screener = html.link('DEX Screener', f'https://dexscreener.com/{network}/{address}')
        links = geckoterminal + html.code(' ' * 3) + dextools + html.code(' ' * 2) + ' ' + dex_screener

        if pool.network is Network.TON:
            def ticker_to_url_ticker(ticker: str):
                return ticker.replace(' ', '+')

            tonviewer = html.link('Tonviewer', f'https://tonviewer.com/{address}')
            swap_coffee = html.link('swap.coffee', f'https://swap.coffee/dex?ft={ticker_to_url_ticker(pool.network.get_name())}&st={ticker_to_url_ticker(ticker)}')
            links += '\n' + tonviewer + html.code(' ' * (width - 18)) + ' ' + swap_coffee

        return '\n'.join([
            html.code('\n'.join(lines)),
            links,
            html.code(pool.base_token.address),
        ])

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
