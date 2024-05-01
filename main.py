# TODO: add github repo, .env guide
# TODO: add documentation
# TODO: add static typing
import logging
import os
import time

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler

from api_wrapper import GeckoTerminalAPIWrapper
from pools import Pools

load_dotenv()
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')


def main():
    pools = Pools()
    api = GeckoTerminalAPIWrapper()

    while True:
        api.update_pools(pools)
        print(pools, end='\n\n')
        time.sleep(10)


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="I'm a bot, please talk to me!")


if __name__ == '__main__':
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    start_handler = CommandHandler('start', start)
    application.add_handler(start_handler)

    application.run_polling()
