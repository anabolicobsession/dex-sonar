from math import floor, log10
from datetime import datetime, timezone


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
    if k_mode: s += K * 'K'; left -= K
    if percent: s += '%'

    return ' ' * max(left, 0) + s + ' ' * max(right, 0)


MINUTE = 60
MINUTE_STR = 'min'

HOUR = MINUTE * 60
HOUR_STR = 'hour'

DAY = HOUR * 24
DAY_STR = 'day'

MONTH = DAY * 30
MONTH_STR = 'month'

YEAR = DAY * 365
YEAR_STR = 'year'

def difference_to_pretty_str(timestamp: datetime):
    seconds = (datetime.now(timezone.utc) - timestamp).total_seconds()

    if seconds < MINUTE * 2:
        return str(int(seconds / MINUTE)) + ' ' + MINUTE_STR
    elif seconds < MINUTE * 60:
        return str(int(seconds / MINUTE)) + ' ' + MINUTE_STR + 's'

    elif seconds < HOUR * 2:
        return str(int(seconds / HOUR)) + ' ' + HOUR_STR
    elif seconds < HOUR * 24:
        return str(int(seconds / HOUR)) + ' ' + HOUR_STR + 's'

    elif seconds < DAY * 2:
        return str(int(seconds / DAY)) + ' ' + DAY_STR
    elif seconds < DAY * 30:
        return str(int(seconds / DAY)) + ' ' + DAY_STR + 's'

    elif seconds < MONTH * 2:
        return str(int(seconds / MONTH)) + ' ' + MONTH_STR
    elif seconds < MONTH * 12:
        return str(int(seconds / MONTH)) + ' ' + MONTH_STR + 's'

    elif seconds < YEAR * 2:
        return str(int(seconds / YEAR)) + ' ' + YEAR_STR
    else:
        return str(int(seconds / YEAR)) + ' ' + YEAR_STR + 's'
