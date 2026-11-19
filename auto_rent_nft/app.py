from __future__ import annotations

import html
import logging
from pathlib import Path

from .api import StarShopAPI
from .config import DEFAULTS
from .core.orders import Orders, until_str
from .core.scheduler import Scheduler
from .core.store import Store
from .funpay.chat import Outbox
from .funpay.lots import Lots
from .texts import Texts

log = logging.getLogger("auto_rent_nft")


def _h(s) -> str:
    return html.escape(str(s or ""))


class NftRent:
    id = "auto_rent_nft"
    name = "NFT Rent"
    version = "1.0.0"

    def __init__(self, app, data_dir: Path, defaults: dict | None = None):
        self.app = app
        self.enabled_fn = lambda: True
        self.defaults = {**DEFAULTS, **(defaults or {})}
        data_dir.mkdir(parents=True, exist_ok=True)
        self.cfg()
        self.store = Store(data_dir / "orders.sqlite")
        self.texts = Texts(self.cfg)
        self.api = StarShopAPI(self.cfg)
        self.lots = Lots(self)
        self.orders = Orders(self)
        self.out = Outbox(app.fp, self._undelivered, self._flood)
        self.scheduler = Scheduler(self)

    def cfg(self) -> dict:
        return self.app.settings.plugin_settings(self.id, self.defaults)

    def cfg_set(self, **values) -> None:
        with self.app.settings.lock:
            self.cfg().update(values)
            self.app.settings.save()

    @property
    def active(self) -> bool:
        return bool(self.enabled_fn()) and bool(self.cfg().get("enabled", True))

    def start(self) -> None:
        self.scheduler.start()

    def stop(self) -> None:
        self.scheduler.stop()

    def on_new_order(self, order) -> bool:
        if not self.active or not self.api.ready:
            return False
        return self.orders.on_new_order(order)

    def on_message(self, msg) -> bool:
        if not self.active:
            return False
        return self.orders.on_message(msg)

    def on_order_status(self, order) -> None:
        from FunPayAPI.common.enums import OrderStatuses
        if getattr(order, "status", None) == OrderStatuses.REFUNDED:
            self.orders.on_refund(str(order.id))

    def _undelivered(self, chat: str, kind: str, text: str) -> None:
        o = self.store.in_chat(chat, ("choosing", "renting", "bind_choice", "bind_manual", "bind_fast", "bind_target",
                                      "paused", "failed", "done"))
        what = (text or "картинка")[:60].replace("\n", " ")
        self.alert(f"Не смог отправить покупателю сообщение «{what}» — FunPay не принимает. Напиши ему сам",
                   o["id"] if o else None)

    def _flood(self, chat: str) -> None:
        o = self.store.in_chat(chat, ("choosing", "renting", "bind_choice", "bind_manual", "bind_fast", "bind_target",
                                      "paused", "failed", "done"))
        self.alert("Защита от спама: в один чат пытались отправить слишком много сообщений, лишние отброшены", o["id"] if o else None)

    def notify(self, kind: str, text: str, buttons: list | None = None) -> None:
        self.app.notify(kind, text, buttons)

    def alert(self, text: str, order_id: str | None = None, kind: str = "errors") -> None:
        log.warning("⚠️ %s", text)
        if not self.cfg().get("notify_errors", True):
            return
        rows = [[("🧾 Заказ", f"url:https://funpay.com/orders/{order_id}/"), ("💎 Карточка", f"nr:o:{order_id}")]] \
            if order_id else None
        self.notify("plugins", f"⚠️ <b>NFT Rent</b>\n{_h(text)}", rows)

    def extended(self, o: dict, days: int) -> None:
        log.info("Заказ %s: продление %s на %s сут до %s", o["id"], o["nft_name"], days, until_str(o["until"]))
        if not self.cfg().get("notify_delivered", True):
            return
        profit = float(o["sum"] or 0) - float(o["cost"] or 0)
        self.notify("delivery",
                    f"🔄 <b>Продление</b>\n━━━━━━━━━━━━━━\n🎁 {_h(o['nft_name'])} · +{days} сут.\n"
                    f"👤 {_h(o['buyer'])}\n⏰ до {until_str(o['until'])}\n"
                    f"💰 {o['sum']:.2f} ₽ · продление {float(o['cost'] or 0):.2f} ₽ · прибыль <b>{profit:.2f} ₽</b>",
                    [[("🧾 Заказ", f"url:https://funpay.com/orders/{o['id']}/")]])

    def delivered(self, o: dict, how: str) -> None:
        log.info("Заказ %s выдан: %s до %s", o["id"], o["nft_name"], until_str(o["until"]))
        if not self.cfg().get("notify_delivered", True):
            return
        tg = o.get("tg") or {}
        who = f"@{tg['username']}" if tg.get("username") else (tg.get("name") or "привязка вручную")
        profit = float(o["sum"] or 0) - float(o["cost"] or 0)
        self.notify("delivery",
                    f"📦 <b>Подарок выдан</b>\n━━━━━━━━━━━━━━\n"
                    f"🎁 {_h(o['nft_name'])}\n👤 {_h(o['buyer'])} · Telegram: {_h(who)}\n"
                    f"⏰ до {until_str(o['until'])} · {'быстро' if how == 'fast' else 'вручную'}\n"
                    f"💰 {o['sum']:.2f} ₽ · аренда {float(o['cost'] or 0):.2f} ₽ · прибыль <b>{profit:.2f} ₽</b>",
                    [[("🎁 NFT", f"url:https://t.me/nft/{o['slug']}")] if o.get("slug") else [],
                     [("🧾 Заказ", f"url:https://funpay.com/orders/{o['id']}/"),
                      ("💬 Чат", f"url:https://funpay.com/chat/?node={o['chat_id']}")]])
