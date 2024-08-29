from enum import Enum, auto
from io import BytesIO
from math import ceil, floor, log10

from aiogram.utils.markdown import code, link
from telegram.constants import ParseMode

from dex_sonar.config.config import USER_TIMEZONE, config
from dex_sonar.network.network import Network
from dex_sonar.network.pool_with_chart import Backend, MaxBinsScheme, PlotSizeScheme, Pool, SizeScheme, TrendsView


Text = str
Image = BytesIO


def clip(x, minimum, maximum):
    return min(max(x, minimum), maximum)


def place_strings_equidistantly_by_beginning(*strings, length, left_indent_bigger=False):
    strings = list(filter(None, strings))

    if len(strings) == 1:
        indent_len, remainder_len = divmod(length, 2)
        return ' ' * indent_len + strings[0] + ' ' * (indent_len + remainder_len)

    else:
        indents_len = length - sum(map(len, strings))
        indent_len, remainder_len = divmod(indents_len, len(strings) - 1)
        indent = ' ' * indent_len
        bigger_indent = ' ' * (indent_len + remainder_len)
        return (
            (
                    indent.join(strings[:-1]) +
                    bigger_indent +
                    strings[-1]
            )
            if not left_indent_bigger else
            (
                    strings[0] +
                    bigger_indent +
                    indent.join(strings[1:])
            )
        )


def place_strings_equidistantly_by_middle(*strings, length, left_indent_bigger=False):
    result = list(' ' * length)
    n = len(strings)

    for i, string in enumerate(strings):
        string_length = len(string)
        position = length * (i / (n - 1)) - string_length / 2
        position = clip(floor(position) if not left_indent_bigger else ceil(position), minimum=0, maximum=length - string_length)
        result[position:position + string_length] = string

    return ''.join(result)


def round_to_significant_figures(x, n=1):
    if x:
        r = -int(floor(log10(abs(x)))) + (n - 1)
        return round(x, r) if r > 0 else int(round(x, r))
    else:
        return x


def format_number(
        x,
        left=0,
        right=0,
        sign=False,
        symbol=None,
        percent=False,
        significant_figures=None,
        significant_figures_no_zeros=False,
        k_mode=None,
):
    if sign: sign = '+' if x > 0 else ('-' if x < 0 else ' ')
    x = abs(x)
    K = None

    if percent: x *= 100
    if significant_figures:
        k_mode = False
        x = round_to_significant_figures(x, significant_figures) if x > 0 else 0
    if k_mode:
        significant_figures = None
        right = 0
        K = max(int(log10(x) // 3) if x > 0 else 1, 1)
        x = int(x // 1000 ** K)

    int_len = len(str(round(x)))
    s = f'{x:{int_len + bool(right) + right}.{right}f}'
    left -= int_len

    if significant_figures:
        if significant_figures_no_zeros and right > 0:
            new_s = s.rstrip('0') if s != '0' else s
            right -= (len(s) - len(new_s))
            s = new_s if new_s[-1] != '.' else new_s[:-1]
            if right > 0: right += int(new_s[-1] != '.')
        else:
            right = 0
        if s == '0': sign = ' '
    elif k_mode:
        s = str(x)
        if sign and s == '0': sign = ' '
        if right: right += 1
    else:
        right = 0

    if symbol: s = symbol + s
    if sign: s = sign + s

    if k_mode and K:
        s += {
            1: 'K',
            2: 'M',
            3: 'B',
            4: 'Q',
        }[K]
        left -= 1

    if percent: s += '%'

    return ' ' * max(left, 0) + s + ' ' * max(right, 0)


class Format(Enum):
    PRICE = auto()
    K_MODE = auto()


def format(x, type: Format):
    match type:
        case Format.PRICE:
            return format_number(x, right=9, symbol='$', significant_figures=2)
        case Format.K_MODE:
            return format_number(x, symbol='$', k_mode=True)


def dex_screener_link(pool: Pool):
    return link('DEX Screener', f'https://dexscreener.com/{pool.network.id}/{pool.address}')


def geckoterminal_link(pool: Pool):
    return link('GeckoTerminal', f'https://www.geckoterminal.com/{pool.network.id}/pools/{pool.address}')


def dextools_link(pool: Pool):
    return link('DEXTools', f'https://www.dextools.io/app/en/{pool.network.id}/pair-explorer/{pool.address}')


def ticker_to_url_ticker(ticker: str):
    return ticker.replace(' ', '+')


def swap_coffee_link(pool: Pool):
    return link('swap.coffee', f'https://swap.coffee/dex?ft={ticker_to_url_ticker(pool.network.native_token_ticker)}&st={ticker_to_url_ticker(pool.base_ticker)}')


def tonviewer_link(pool: Pool):
    return link('Tonviewer', f'https://tonviewer.com/{pool.address}')


class Type(Enum):
    PATTERN = auto()
    ARBITRAGE = auto()


class Message:

    PARSE_MODE: ParseMode = ParseMode.MARKDOWN_V2

    def __init__(
            self,
            type: Type,
            pool: Pool,
            additional_pool: Pool = None,
            attention_text: str = None,
            line_width: int = config.getint('Message', 'width'),
    ):
        self.text = self._create_text_message(
            type,
            pool,
            additional_pool,
            attention_text,
            line_width,
        )
        self.image = self._create_chart_image(
            pool,
        )

    def has_text(self):
        return self.text is not None

    def has_image(self):
        return self.image is not None

    def get_text(self) -> Text:
        return self.text

    def get_image(self) -> Image:
        self.image.seek(0)
        return self.image

    @staticmethod
    def _create_text_message(
            type: Type,
            pool: Pool,
            additional_pool: Pool = None,
            attention_text: str = None,
            line_width: int = config.getint('Message', 'width'),
    ) -> Text:
        lines = []
        links = []

        def add_line(*strings, length=None, by_middle=False, left_indent_bigger=False):
            if not by_middle:
                lines.append(place_strings_equidistantly_by_beginning(*strings, length=length if length else line_width, left_indent_bigger=left_indent_bigger))
            else:
                lines.append(place_strings_equidistantly_by_middle(*strings, length=length if length else line_width, left_indent_bigger=left_indent_bigger))

        def add_link_line(line_line):
            links.append(line_line)

        add_line(pool.form_name(shortened_if_native=True), attention_text)

        match type:

            case Type.PATTERN:
                add_line('Price:', format(pool.price_usd, Format.PRICE))
                add_line('FDV:', format(pool.fdv, Format.K_MODE))
                add_line('Volume:', format(pool.volume, Format.K_MODE))
                add_line('Liquidity:', format(pool.liquidity, Format.K_MODE))
                add_line('Age:', pool.creation_date.time_elapsed().to_human_readable_format())

                match pool.network:
                    case Network.TON:
                        add_link_line(tonviewer_link(pool) + code(' ' * (line_width - 18)) + ' ' + swap_coffee_link(pool))

                add_link_line(dextools_link(pool) + code(' ' * 3) + geckoterminal_link(pool) + code(' ' * 2) + ' ' + dex_screener_link(pool))

            case Type.ARBITRAGE:
                add_line(f'{pool.quote_ticker} ({pool.dex_name})', '->', f'{additional_pool.quote_ticker} ({additional_pool.dex_name})', by_middle=True, left_indent_bigger=True)
                add_line(format(pool.price_usd, Format.PRICE), 'Price', format(additional_pool.price_usd, Format.PRICE), by_middle=True, left_indent_bigger=True)
                add_line(format(pool.fdv, Format.K_MODE), 'FDV', format(additional_pool.fdv, Format.K_MODE), by_middle=True, left_indent_bigger=True)
                add_line(format(pool.volume, Format.K_MODE), 'Volume', format(additional_pool.volume, Format.K_MODE), by_middle=True, left_indent_bigger=True)
                add_line(format(pool.liquidity, Format.K_MODE), 'Liquidity', format(additional_pool.liquidity, Format.K_MODE), by_middle=True, left_indent_bigger=True)
                add_line(pool.creation_date.time_elapsed().to_human_readable_format(), 'Age', additional_pool.creation_date.time_elapsed().to_human_readable_format(), by_middle=True, left_indent_bigger=True)

                match pool.network:
                    case Network.TON:
                        add_link_line(code(' ' * floor(line_width / 2.62)) + swap_coffee_link(pool))

                add_link_line(geckoterminal_link(pool) + code(' ' * floor(line_width / 3)) + ' ' + geckoterminal_link(additional_pool))
                add_link_line(dex_screener_link(pool) + code(' ' * floor(line_width / 2.5)) + dex_screener_link(additional_pool))

        return '\n'.join(
            filter(
                None,
                [
                    code('\n'.join(lines)),
                    '\n'.join(links),
                    code(pool.base_token.address),
                ]
            )
        )

    @staticmethod
    def _create_chart_image(pool: Pool) -> Image:
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
            ) as (plt, fig, _, _)
        ):
            buffer = BytesIO()
            fig.savefig(
                buffer,
                format='png',
                dpi=150,
                bbox_inches='tight',
                pad_inches=0.3,
            )
            return buffer
