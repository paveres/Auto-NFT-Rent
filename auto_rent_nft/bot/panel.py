from __future__ import annotations

import asyncio
import html
import time
from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..api import ApiError
from ..config import STATE_RU
from ..core.orders import days_str, until_str
from ..texts import DEFAULT_TEXTS, TITLES, VARIABLES
from .ui import LINE, back, kb, onoff, show

if TYPE_CHECKING:
    from ..app import NftRent

PAGE = 8
DOCS = "https://docs.rusksmm.ru"
TOGGLES = {
    "notify_delivered": "🔔 Уведомлять о выдаче",
    "notify_errors": "🔔 Уведомлять о проблемах",
    "auto_raise": "⬆️ Автоподнятие лотов",
}


def h(s) -> str:
    return html.escape(str(s if s is not None else ""))


def mask(s: str) -> str:
    s = str(s or "")
    return "—" if not s else (s[:3] + "•" * max(0, len(s) - 5) + s[-2:] if len(s) > 5 else "•" * len(s))


class NftPanel:
    def __init__(self, plugin: "NftRent", panel):
        self.p = plugin
        self.panel = panel

    async def home_view(self):
        c = self.p.cfg()
        bal = "—"
        if self.p.api.ready:
            try:
                bal = f"{await asyncio.to_thread(self.p.api.balance):.2f} ₽"
                api = "✅ подключён"
            except ApiError as e:
                api = f"⚠️ {h(e.message[:60])}"
        else:
            api = "❌ не задан"
        try:
            gifts = await asyncio.to_thread(self.p.lots.listed) if self.p.api.ready else []
        except Exception:
            gifts = []
        on = sum(1 for g in gifts if g.get("active", True))
        db = self.p.store
        work = db.value("SELECT COUNT(*) FROM orders WHERE state IN ('choosing','renting','bind_choice','bind_manual',"
                        "'bind_fast','bind_target','failed')") or 0
        done = db.value("SELECT COUNT(*) FROM orders WHERE state='done'") or 0
        text = (f"💎 <b>NFT Rent · Аренда NFT</b>\n{LINE}\n"
                f"🧩 Плагин: <b>{onoff(self.p.active)} {'ВКЛ' if self.p.active else 'ВЫКЛ'}</b>\n"
                f"🔑 API: <b>{api}</b>\n"
                f"💰 Баланс API: <b>{bal}</b>\n"
                f"🎁 Лоты: <b>{on} активных / {len(gifts)} всего</b>\n"
                f"🕒 Заказы: <b>{work} в работе · {done} выдано</b>\n{LINE}\n"
                "<i>Выберите раздел:</i>")
        markup = kb([("🔑 Ключ API", "nr:key"), ("⚙️ Настройки", "nr:set")],
                    [(f"🎁 Лоты · {len(gifts)}", "nr:lots"), ("🕒 Заказы", "nr:ord:0")],
                    [("💬 Сообщения", "nr:msg:0"), ("📊 Статистика", "nr:stats")],
                    [(f"{onoff(c.get('enabled', True))} Включить / выключить", "nr:onoff")],
                    back(*getattr(self.panel, "nr_back", None)) if getattr(self.panel, "nr_back", None) else [])
        return text, markup

    def key_view(self):
        c = self.p.cfg()
        text = (f"🔑 <b>Ключ API StarShop</b>\n{LINE}\n"
                f"🌐 Адрес: <code>{h(c['api_url'])}</code>\n"
                f"🎫 Токен: <code>{h(mask(c['api_token']))}</code>\n"
                f"🔢 PIN: <code>{h(mask(c['api_pin']))}</code>\n{LINE}\n"
                "Ключ и PIN выдаёт @BlimyStarsBot → Профиль → API.\n"
                "Аренда списывается с баланса API этого ключа.")
        return text, kb([("✏️ Токен", "nr:in:api_token"), ("✏️ PIN", "nr:in:api_pin")],
                        [("✏️ Адрес API", "nr:in:api_url"), ("🔄 Проверить", "nr:keytest")],
                        [("📖 Документация API", f"url:{DOCS}")], back("nr:home"))

    def set_view(self):
        c = self.p.cfg()
        lines = [f"⚙️ <b>Настройки</b>\n{LINE}"]
        lines += [f"{t}: <b>{onoff(c[k])}</b>" for k, t in TOGGLES.items()]
        rows = [[(f"{onoff(c[k])} {t}", f"nr:tg:{k}")] for k, t in TOGGLES.items()]
        return "\n".join(lines), kb(*rows, back("nr:home"))

    def own_lots_view(self):
        self.p.lots._own = (0, None)
        offers = self.p.lots.own_offers()
        lines = [f"🎁 <b>Свои лоты</b>\n{LINE}",
                 "Плагин ведёт заказы по вашим лотам, где в описании есть <code>!rent</code>.",
                 "В названии лота — название подарка как в Telegram и срок, например:",
                 "<code>Plush Pepe · аренда 1 день</code> или <code>Snoop Dogg — аренда 3 дня</code>",
                 "Количество в заказе = во сколько раз умножить срок.", LINE,
                 f"Найдено лотов аренды: <b>{len(offers)}</b>"]
        lines += [f"• {h(o['name'])} · {o['buyer_price']:.2f} ₽ · <code>{o['offer_id']}</code>" for o in offers[:30]]
        return "\n".join(lines), kb([("🔄 Обновить", "nr:lots")], back("nr:home"))

    def orders_view(self, page: int = 0):
        db = self.p.store
        total = db.value("SELECT COUNT(*) FROM orders") or 0
        rows_db = db.rows("SELECT * FROM orders ORDER BY CASE WHEN state IN ('done','refunded') THEN 1 ELSE 0 END, "
                          "created DESC LIMIT ? OFFSET ?", PAGE, page * PAGE)
        pages = max(1, -(-total // PAGE))
        icon = {"done": "✅", "failed": "⚠️", "refunded": "↩️", "paused": "⏸"}
        text = f"🕒 <b>Заказы</b>\n{LINE}\nВсего: <b>{total}</b>. Сверху — те, что в работе."
        rows = [[(f"{icon.get(o['state'], '⏳')} #{o['id']} · {o['nft_name'] or o['gift']} · {STATE_RU.get(o['state'], o['state'])}",
                  f"nr:o:{o['id']}")] for o in rows_db]
        nav = []
        if page > 0:
            nav.append(("◀️", f"nr:ord:{page - 1}"))
        if pages > 1:
            nav.append((f"{page + 1}/{pages}", "nr:noop"))
        if page < pages - 1:
            nav.append(("▶️", f"nr:ord:{page + 1}"))
        rows.append(nav)
        return text, kb(*rows, back("nr:home"))

    def order_view(self, oid: str):
        o = self.p.store.order(oid)
        if not o:
            return "Заказ не найден.", kb(back("nr:ord:0"))
        tg = o["tg"] or {}
        lines = [f"💎 <b>Заказ #{h(o['id'])}</b>\n{LINE}",
                 f"👤 Покупатель: <b>{h(o['buyer'])}</b>",
                 f"🎁 {h(o['gift'])} · {days_str(o['days'])} · {o['sum']:.2f} ₽",
                 f"📌 Статус: <b>{STATE_RU.get(o['state'], o['state'])}</b>"]
        if o["nft_name"]:
            lines.append(f"🖼 NFT: {h(o['nft_name'])}" + (f" · аренда <code>{h(o['rental'])}</code>" if o["rental"] else ""))
        if o["cost"]:
            lines.append(f"💰 Аренда {o['cost']:.2f} ₽ · прибыль <b>{o['sum'] - o['cost']:.2f} ₽</b>")
        if o["until"]:
            lines.append(f"⏰ До {until_str(o['until'])}")
        if tg:
            lines.append(f"✈️ Telegram: {h('@' + tg['username'] if tg.get('username') else tg.get('name') or tg.get('id'))}")
        if o["note"]:
            lines.append(f"⚠️ {h(o['note'])}")
        rows = []
        if o["state"] in ("failed", "paused"):
            rows.append([("🔁 Повторить", f"nr:or:{oid}")])
        if o["state"] in ("bind_choice", "bind_manual", "bind_fast", "bind_target", "done") and o["rental"]:
            rows.append([("🔗 Привязка заново", f"nr:ob:{oid}")])
        rows.append([("🧾 Заказ", f"url:https://funpay.com/orders/{oid}/"),
                     ("💬 Чат", f"url:https://funpay.com/chat/?node={o['chat_id']}")])
        return "\n".join(lines), kb(*rows, back("nr:ord:0"))

    def msgs_view(self, page: int = 0):
        keys = list(DEFAULT_TEXTS)
        pages = -(-len(keys) // 10)
        custom = self.p.cfg().get("texts") or {}
        text = (f"💬 <b>Сообщения покупателю</b>\n{LINE}\n"
                f"✏️ — изменено вами. Переменные: <code>{VARIABLES}</code>")
        rows = [[(f"{'✏️ ' if k in custom else ''}{TITLES.get(k, k)}", f"nr:mt:{k}")] for k in keys[page * 10:(page + 1) * 10]]
        nav = []
        if page > 0:
            nav.append(("◀️", f"nr:msg:{page - 1}"))
        nav.append((f"{page + 1}/{pages}", "nr:noop"))
        if page < pages - 1:
            nav.append(("▶️", f"nr:msg:{page + 1}"))
        rows.append(nav)
        return text, kb(*rows, back("nr:home"))

    def msg_view(self, key: str):
        custom = (self.p.cfg().get("texts") or {}).get(key)
        text = (f"💬 <b>{h(TITLES.get(key, key))}</b> {'· ✏️ изменено' if custom else '· по умолчанию'}\n{LINE}\n"
                f"<code>{h(self.p.texts.raw(key))}</code>")
        rows = [[("✏️ Изменить", f"nr:in:txt:{key}")]]
        if custom:
            rows.append([("↩️ Вернуть по умолчанию", f"nr:mr:{key}")])
        return text, kb(*rows, back("nr:msg:0"))

    def stats_view(self):
        db = self.p.store
        day0 = time.time() - 86400
        q = "SELECT COUNT(*) n, COALESCE(SUM(sum),0) s, COALESCE(SUM(cost),0) c FROM orders WHERE state='done'"
        all_ = db.rows(q)[0]
        today = db.rows(q + " AND created>?", day0)[0]
        fails = db.value("SELECT COUNT(*) FROM orders WHERE state='failed'") or 0
        text = (f"📊 <b>Статистика NFT Rent</b>\n{LINE}\n"
                f"Выдано всего: <b>{all_['n']}</b> на <b>{all_['s']:.2f} ₽</b>\n"
                f"Аренда обошлась: {all_['c']:.2f} ₽ · прибыль <b>{all_['s'] - all_['c']:.2f} ₽</b>\n\n"
                f"За сутки: <b>{today['n']}</b> на {today['s']:.2f} ₽ · прибыль {today['s'] - today['c']:.2f} ₽\n"
                f"Нужна помощь: <b>{fails}</b>")
        return text, kb([("🔄 Обновить", "nr:stats")], back("nr:home"))

    def _inputs(self):
        async def on_input(m: Message, data: dict):
            field = data.get("field", "")
            raw = (m.text or "").strip()
            if field.startswith("txt:"):
                key = field[4:]
                texts = dict(self.p.cfg().get("texts") or {})
                texts[key] = m.html_text if m.html_text else raw
                self.p.cfg_set(texts=texts)
                return self.msg_view(key)
            if field in ("api_token", "api_pin", "api_url"):
                if field == "api_pin" and not (raw.isdigit() and len(raw) == 5):
                    return "⚠️ PIN — 5 цифр."
                if field == "api_token" and len(raw) != 12:
                    return "⚠️ Токен — 12 символов."
                self.p.cfg_set(**{field: raw.rstrip("/") if field == "api_url" else raw})
                try:
                    await m.delete()
                except Exception:
                    pass
                return self.key_view()
            return None

        self.panel.register_input("nr_input", on_input)

    def router(self) -> Router:
        r = Router()
        self._inputs()

        @r.message(Command("nftrent"))
        async def cmd(m: Message):
            text, markup = await self.home_view()
            await m.answer(text, reply_markup=markup)

        @r.callback_query(F.data == "nr:home")
        async def home(cb: CallbackQuery):
            await show(cb, *(await self.home_view()))

        @r.callback_query(F.data == "nr:noop")
        async def noop(cb: CallbackQuery):
            await cb.answer()

        @r.callback_query(F.data == "nr:onoff")
        async def onoff_cb(cb: CallbackQuery):
            self.p.cfg_set(enabled=not self.p.cfg().get("enabled", True))
            await show(cb, *(await self.home_view()))

        @r.callback_query(F.data == "nr:key")
        async def key(cb: CallbackQuery):
            await show(cb, *self.key_view())

        @r.callback_query(F.data == "nr:keytest")
        async def keytest(cb: CallbackQuery):
            try:
                d = await asyncio.to_thread(self.p.api.me)
                cl, lim = d["client"], d["limits"]
                await cb.answer(f"✅ Работает. Баланс {cl['balance_rub']} ₽, лимит {lim['per_minute']}/мин", show_alert=True)
            except ApiError as e:
                await cb.answer(f"⚠️ {e.message[:180]}", show_alert=True)

        @r.callback_query(F.data.startswith("nr:in:"))
        async def ask(cb: CallbackQuery, state: FSMContext):
            field = cb.data[6:]
            if field.startswith("txt:"):
                prompt = (f"✏️ Пришлите новый текст «{h(TITLES.get(field[4:], field[4:]))}».\n"
                          f"Переменные: <code>{VARIABLES}</code>")
                backto = f"nr:mt:{field[4:]}"
            else:
                prompt = {"api_token": "🎫 Пришлите токен API (12 символов).", "api_pin": "🔢 Пришлите PIN (5 цифр).",
                          "api_url": "🌐 Пришлите адрес API, например https://api.rusksmm.ru/v1"}[field]
                backto = "nr:key"
            await self.panel.ask(cb, state, "nr_input", prompt, back=backto, field=field)

        @r.callback_query(F.data == "nr:set")
        async def settings(cb: CallbackQuery):
            await show(cb, *self.set_view())

        @r.callback_query(F.data.startswith("nr:tg:"))
        async def toggle(cb: CallbackQuery):
            k = cb.data[6:]
            if k in TOGGLES:
                self.p.cfg_set(**{k: not self.p.cfg().get(k)})
            await show(cb, *self.set_view())

        @r.callback_query(F.data == "nr:lots")
        async def lots(cb: CallbackQuery):
            try:
                await show(cb, *(await asyncio.to_thread(self.own_lots_view)))
            except Exception as e:
                await cb.answer(f"⚠️ {str(e)[:150]}", show_alert=True)

        @r.callback_query(F.data.startswith("nr:ord:"))
        async def orders(cb: CallbackQuery):
            await show(cb, *self.orders_view(int(cb.data.split(":")[2])))

        @r.callback_query(F.data.startswith("nr:o:"))
        async def order(cb: CallbackQuery):
            await show(cb, *self.order_view(cb.data[5:]))

        @r.callback_query(F.data.startswith("nr:or:"))
        async def order_retry(cb: CallbackQuery):
            oid = cb.data[6:]
            ok = self.p.orders.retry(oid)
            await cb.answer("🔁 Запустил заново" if ok else "Сейчас нельзя", show_alert=not ok)
            await show(cb, *self.order_view(oid))

        @r.callback_query(F.data.startswith("nr:ob:"))
        async def order_bind(cb: CallbackQuery):
            oid = cb.data[6:]
            o = self.p.store.order(oid)
            if o:
                self.p.orders.stop_fast(oid)
                self.p.store.upd(oid, state="bind_choice")
                self.p.out.text(o["chat_id"], self.p.texts("bind_choice"))
            await cb.answer("Покупателю отправлен выбор привязки")
            await show(cb, *self.order_view(oid))

        @r.callback_query(F.data.startswith("nr:msg:"))
        async def msgs(cb: CallbackQuery):
            await show(cb, *self.msgs_view(int(cb.data.split(":")[2])))

        @r.callback_query(F.data.startswith("nr:mt:"))
        async def msg(cb: CallbackQuery):
            await show(cb, *self.msg_view(cb.data[6:]))

        @r.callback_query(F.data.startswith("nr:mr:"))
        async def msg_reset(cb: CallbackQuery):
            key = cb.data[6:]
            texts = dict(self.p.cfg().get("texts") or {})
            texts.pop(key, None)
            self.p.cfg_set(texts=texts)
            await show(cb, *self.msg_view(key))

        @r.callback_query(F.data == "nr:stats")
        async def stats(cb: CallbackQuery):
            await show(cb, *self.stats_view())

        return r
