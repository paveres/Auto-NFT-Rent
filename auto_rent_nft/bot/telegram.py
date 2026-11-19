from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import BaseFilter, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardMarkup, Message, TelegramObject

from .panel import NftPanel
from .ui import kb, show

log = logging.getLogger("auto_rent_nft.telegram")


class Input(StatesGroup):
    wait = State()


class IsAdmin(BaseFilter):
    def __init__(self, ids: list[int]):
        self.ids = ids

    async def __call__(self, event: TelegramObject) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user) and user.id in self.ids


class TelegramPanel:
    def __init__(self, token: str, access, plugin):
        self.bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
        self.access = access
        self.admins = access.admins
        self.p = plugin
        self.dp = Dispatcher()
        self.inputs: dict[str, Callable[[Message, dict], Awaitable]] = {}
        self.loop: asyncio.AbstractEventLoop | None = None
        self.nr_back = None

    def register_input(self, key: str, handler) -> None:
        self.inputs[key] = handler

    async def ask(self, event, state: FSMContext, key: str, prompt: str, back: str = "nr:home", **data) -> None:
        await state.set_state(Input.wait)
        await state.set_data({"key": key, "back": back, **data})
        markup = kb([("✖️ Отмена", "nr:incancel")])
        if isinstance(event, CallbackQuery):
            await event.message.answer(prompt, reply_markup=markup)
            await event.answer()
        else:
            await event.answer(prompt, reply_markup=markup)

    def notify(self, kind: str, text: str, buttons: list | None = None) -> None:
        if self.loop is None or self.loop.is_closed():
            return
        markup = kb(*buttons) if buttons else None
        asyncio.run_coroutine_threadsafe(self.broadcast(text, markup), self.loop)

    async def broadcast(self, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
        for chat in self.admins:
            for _ in range(3):
                try:
                    await self.bot.send_message(chat, text[:4096], reply_markup=markup)
                    break
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                except TelegramForbiddenError:
                    log.warning("Админ %s не нажал «Старт» у бота", chat)
                    break
                except Exception as e:
                    log.error("Telegram %s: %s", chat, e)
                    break

    def build(self) -> None:
        admin = Router(name="admin")
        admin.message.filter(IsAdmin(self.admins))
        admin.callback_query.filter(IsAdmin(self.admins))
        ui = NftPanel(self.p, self)

        @admin.message(CommandStart())
        async def start(m: Message, state: FSMContext):
            await state.clear()
            text, markup = await ui.home_view()
            await m.answer(text, reply_markup=markup)

        @admin.callback_query(F.data == "nr:incancel")
        async def cancel(cb: CallbackQuery, state: FSMContext):
            data = await state.get_data()
            await state.clear()
            await show(cb, "✖️ Отменено.", kb([("⬅️ Назад", data.get("back", "nr:home"))]))

        @admin.message(Input.wait)
        async def got_input(m: Message, state: FSMContext):
            data = await state.get_data()
            await state.clear()
            handler = self.inputs.get(data.get("key", ""))
            if handler is None:
                return
            try:
                result = await handler(m, data)
            except Exception as e:
                log.exception("Ввод %s", data.get("key"))
                result = f"⚠️ Ошибка: {e}"
            if isinstance(result, tuple):
                await m.answer(result[0], reply_markup=result[1])
            elif result:
                await m.answer(result, reply_markup=kb([("⬅️ Назад", data.get("back", "nr:home"))]))

        admin.include_router(ui.router())
        guest = Router(name="guest")

        @guest.message()
        async def stranger(m: Message):
            uid = m.from_user.id
            text = (m.text or "").strip()
            if not self.access.password:
                await m.answer("⛔ Пароль панели не задан. Выполните python main.py setup и придумайте пароль.")
                return
            if text.startswith("/start"):
                await m.answer("🔒 Личная панель NFT Rent. Пришлите пароль, который вы задали при настройке.")
                return
            res = self.access.login(uid, text)
            try:
                await m.delete()
            except Exception:
                pass
            if res == "ok":
                view, markup = await ui.home_view()
                await m.answer("✅ Доступ открыт. Уведомления о заказах и оплатах будут приходить сюда.")
                await m.answer(view, reply_markup=markup)
            elif res == "locked":
                await m.answer("⛔ Слишком много попыток. Подождите 10 минут.")
            else:
                await m.answer(f"❌ Неверный пароль. Осталось попыток: {self.access.left(uid)}")

        self.dp.include_routers(admin, guest)

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.build()
        me = await self.bot.get_me()
        log.info("Бот Telegram: @%s", me.username)
        await self.bot.set_my_commands([BotCommand(command="start", description="💎 Меню NFT Rent")])
        await self.broadcast("🟢 <b>NFT Rent запущен</b>\nМеню — /start")
        await self.dp.start_polling(self.bot, handle_signals=False)
