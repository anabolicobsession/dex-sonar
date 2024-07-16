from asyncio import run
from io import BytesIO
from typing import Awaitable, Iterable

from telegram import Bot as TelegramBot, LinkPreviewOptions, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Defaults, ApplicationBuilder, BaseHandler


class Bot:
    def __init__(self, token, token_silent):
        defaults = Defaults(
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        self.application = ApplicationBuilder().token(token).defaults(defaults).build()
        self.application_silent = ApplicationBuilder().token(token_silent).defaults(defaults).build()
        self.bot: TelegramBot = self.application.bot
        self.bot_silent: TelegramBot = self.application_silent.bot

    def add_handlers(self, handlers: Iterable[BaseHandler]):
        self.application.add_handlers(handlers)
        self.application_silent.add_handlers(handlers)

    def run(self, coroutine: Awaitable):
        run(self._run(coroutine))

    async def _run(self, coroutine: Awaitable):
        async with self.application:
            await self.application.start()
            await self.application.updater.start_polling()

            async with self.application_silent:
                await self.application_silent.start()
                await self.application_silent.updater.start_polling()

                await coroutine

                await self.application_silent.updater.stop()
                await self.application_silent.stop()

            await self.application.updater.stop()
            await self.application.stop()

    def is_silent(self, bot: TelegramBot):
        return bot is self.bot_silent

    async def set_description(self, description):
        await self.bot.set_my_short_description(description)
        await self.bot_silent.set_my_short_description(description)

    async def send_message(
            self,
            user_id,
            text,
            image: BytesIO = None,
            reply_markup: InlineKeyboardMarkup = None,
            silent: bool = False,
            bot: TelegramBot = None
    ):
        if not bot:
            bot = self.bot if not silent else self.bot_silent
        else:
            silent = bot is self.bot_silent

        if not image:
            await bot.send_message(
                user_id,
                text,
                reply_markup=reply_markup,
                disable_notification=silent,
            )
        else:
            image.seek(0)
            await bot.send_photo(
                user_id,
                image,
                text,
                reply_markup=reply_markup,
                disable_notification=silent,
            )
