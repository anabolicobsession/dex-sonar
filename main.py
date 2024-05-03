import asyncio
import logging
import os
import timeit
from asyncio import CancelledError

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

import settings
from gecko_terminal_api_wrapper import GeckoTerminalAPIWrapper
from pools import Pools, Pool

bot_users = settings.DEFAULT_BOT_USERS

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text='Hey there! I am using WhatsApp\nAll prices are in TON!')


def foo(n, places=0, sign=False) -> str:
    places += sign

    if n < 10000:
        return f'{int(n):{"+" if sign else ""}{places}}'
    else:
        K = (len(str(int(n))) - 1) // 3
        new_n = round(n / (1000 ** K), 1)
        point = str(new_n)[-1] != '0'
        return f'{new_n:{"+" if sign else ""}{max(places - K, 0)}.{int(point)}f}' + 'K' * K


def pool_to_message(p: Pool, i):
    place_number = f'{i:{len(str(settings.MAX_GROWING_POOLS_IN_MESSAGE))}d}'
    link = f'<a href="https://www.geckoterminal.com/{p.network}/pools/{p.address}">Link</a>'
    l1 = f'<code>{place_number}. {p.get_pretty_name():<9} {p.relative_price:13.9f} {p.network.upper()}</code>  {link}'

    places = 3

    m5 = foo(p.price_change.m5 * 100, places, sign=True) + '%'
    h1 = foo(p.price_change.h1 * 100, places, sign=True) + '%'
    h24 = foo(p.price_change.h24 * 100, places, sign=True) + '%'
    l2 = f'<code>Price change:  {m5} {h1} {h24}</code>'

    m5 = foo(p.buy_sell.m5 * 100, places, sign=True) + '%'
    h1 = foo(p.buy_sell.h1 * 100, places, sign=True) + '%'
    h24 = foo(p.buy_sell.h24 * 100, places, sign=True) + '%'
    l3 = f'<code>Buy/sell: {" " * 5}{m5} {h1} {h24}</code>'

    vol = f'VOL: {"$" + str(foo(p.volume, places=5)):8}'
    fdv = f'FDV: {"$" + str(foo(p.fdv, places=4)):<10}'
    l4 = f'<code>{fdv} {vol}</code>'

    l5 = f'<code>Reserve: {" " * 12}${foo(p.reserve, places=4)}</code>'

    return '\n'.join([l1, l2, l3, l4, l5])


async def run_infinite_loop(bot):
    pools = Pools()
    api = GeckoTerminalAPIWrapper()
    global bot_users

    try:
        while True:
            start_time = timeit.timeit()
            growing_pools = api.update_pools(pools, settings.DEFAULT_NETWORK).find_growing_pools()[:settings.MAX_GROWING_POOLS_IN_MESSAGE]
            growing_pools.sort(key=lambda p: p.price_change.m5)

            if len(growing_pools) > 0:
                message = 'Growing pools:'

                for i, p in enumerate(growing_pools):
                    message += '\n\n' + pool_to_message(p, len(growing_pools) -   i)

                for id in bot_users:
                    try: await bot.send_message(chat_id=id, text=message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                    except Exception as e: print(e)

            elapsed_time = timeit.timeit() - start_time
            cooldown = max(settings.SEND_MESSAGE_EVERY_SECONDS - elapsed_time, 0)
            await asyncio.sleep(cooldown)
    except (CancelledError, KeyboardInterrupt, SystemExit):
        print('interruption caught')


async def main():
    application = ApplicationBuilder().token(os.environ.get('BOT_TOKEN')).build()
    start_handler = CommandHandler('start', start)
    application.add_handler(start_handler)

    async with application:
        await application.start()
        await application.updater.start_polling()
        await run_infinite_loop(application.bot)
        await application.updater.stop()
        await application.stop()


if __name__ == '__main__':
    asyncio.run(main())
