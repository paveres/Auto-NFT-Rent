from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, Message

LINE = "━━━━━━━━━━━━━━"


def btn(text: str, action: str) -> InlineKeyboardButton:
    if action.startswith("url:"):
        return InlineKeyboardButton(text=text, url=action[4:])
    if action.startswith("copy:"):
        return InlineKeyboardButton(text=text, copy_text=CopyTextButton(text=action[5:][:256]))
    if action.startswith("cb:"):
        action = action[3:]
    return InlineKeyboardButton(text=text, callback_data=action[:64])


def kb(*rows) -> InlineKeyboardMarkup:
    out = []
    for row in rows:
        if not row:
            continue
        if isinstance(row, tuple):
            row = [row]
        out.append([btn(t, a) for t, a in row])
    return InlineKeyboardMarkup(inline_keyboard=out)


def back(action: str = "nr:home", text: str = "⬅️ Назад") -> list:
    return [(text, action)]


def onoff(value: bool) -> str:
    return "🟢" if value else "🔴"


async def show(event: CallbackQuery | Message, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as e:
            if "not modified" not in str(e):
                await event.message.answer(text, reply_markup=markup)
        try:
            await event.answer()
        except TelegramBadRequest:
            pass
    else:
        await event.answer(text, reply_markup=markup)
