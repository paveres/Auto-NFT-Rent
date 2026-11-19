from __future__ import annotations

import logging
import threading
import time

from FunPayAPI import Account, Runner
from FunPayAPI.common import exceptions
from FunPayAPI.common.enums import MessageTypes, SubCategoryTypes
from FunPayAPI.updater.events import NewMessageEvent, NewOrderEvent, OrderStatusChangedEvent

from ..config import NODE

log = logging.getLogger("auto_rent_nft.funpay")
SESSION_REFRESH = 40 * 60


def short_error(e: Exception) -> str:
    code = getattr(e, "status_code", None)
    if code in (401, 403):
        return f"FunPay отказал в доступе (код {code}) — golden_key неверный или устарел"
    if hasattr(e, "short_str"):
        try:
            return e.short_str()
        except Exception:
            pass
    return " ".join(str(e).split())[:200]


class FunPay:
    def __init__(self, golden_key: str, user_agent: str = "", proxy: dict | None = None):
        self.golden_key, self.user_agent, self.proxy = golden_key, user_agent, proxy
        self.account: Account | None = None
        self.runner: Runner | None = None
        self.lock = threading.RLock()
        self._last_send: dict[str, float] = {}

    @property
    def my_id(self):
        return getattr(self.account, "id", None)

    @property
    def username(self) -> str:
        return getattr(self.account, "username", "") or ""

    def connect(self) -> None:
        self.account = Account(self.golden_key, user_agent=self.user_agent or None, requests_timeout=20, proxy=self.proxy)
        self.account.get()
        if not self.account.username:
            raise RuntimeError("FunPay не принял golden_key")
        self.runner = Runner(self.account)
        threading.Thread(target=self.runner.loop, name="runner-loop", daemon=True).start()
        log.info("Вход в FunPay: %s (id %s)", self.account.username, self.account.id)

    def refresh_session(self) -> None:
        with self.lock:
            self.account.get(update_phpsessid=True)

    def get_order(self, order_id: str, attempts: int = 3):
        for attempt in range(attempts):
            try:
                with self.lock:
                    return self.account.get_order(str(order_id))
            except Exception as e:
                log.warning("Заказ #%s не открылся (%d/%d): %s", order_id, attempt + 1, attempts, short_error(e))
                time.sleep(2)
        return None

    def send(self, chat_id, text: str, attempts: int = 3) -> bool:
        key = str(chat_id)
        for attempt in range(1, attempts + 1):
            wait = 1.0 - (time.time() - self._last_send.get(key, 0.0))
            if wait > 0:
                time.sleep(wait)
            try:
                with self.lock:
                    self.account.send_message(int(key) if key.isdigit() else key, text)
                self._last_send[key] = time.time()
                return True
            except Exception as e:
                log.warning("Не ушло сообщение в чат %s (%d/%d): %s", chat_id, attempt, attempts, short_error(e))
                time.sleep(2 * attempt)
        return False


class Events:
    def __init__(self, fp: FunPay, plugin, stopping: threading.Event, poll_delay: float = 4.0):
        self.fp, self.p, self.stopping, self.delay = fp, plugin, stopping, poll_delay

    def start(self) -> None:
        for target, name in ((self._events, "fp-events"), (self._session, "fp-session"), (self._raise, "fp-raise")):
            threading.Thread(target=target, name=name, daemon=True).start()

    def _events(self) -> None:
        while not self.stopping.is_set():
            try:
                for event in self.fp.runner.listen(requests_delay=self.delay):
                    if self.stopping.is_set():
                        return
                    self.dispatch(event)
            except Exception as e:
                log.warning("Сбой получения событий FunPay: %s — повтор через 10 с", short_error(e))
                self.stopping.wait(10)

    def dispatch(self, event) -> None:
        try:
            if isinstance(event, NewOrderEvent):
                log.info("💰 Новый заказ #%s от %s: %s", event.order.id, event.order.buyer_username,
                         (event.order.description or "")[:80])
                if self.p.on_new_order(event.order):
                    self.p.notify("new_order", f"💰 <b>Новый заказ</b> #{event.order.id} · {event.order.buyer_username}\n"
                                               f"📦 {(event.order.description or '')[:200]}\n💵 {event.order.price} ₽",
                                  [[("🧾 Заказ", f"url:https://funpay.com/orders/{event.order.id}/"),
                                    ("💎 Карточка", f"nr:o:{event.order.id}")]])
            elif isinstance(event, NewMessageEvent):
                msg = event.message
                if getattr(msg, "by_bot", False) or msg.author_id == self.fp.my_id or not msg.author_id:
                    return
                if getattr(msg, "type", None) not in (None, MessageTypes.NON_SYSTEM):
                    return
                self.p.on_message(msg)
            elif isinstance(event, OrderStatusChangedEvent):
                self.p.on_order_status(event.order)
        except Exception:
            log.exception("Ошибка обработки события %s", type(event).__name__)

    def _session(self) -> None:
        while not self.stopping.wait(SESSION_REFRESH):
            try:
                self.fp.refresh_session()
            except Exception as e:
                log.warning("Сессия FunPay не обновилась: %s", short_error(e))

    def _raise(self) -> None:
        wait = 30
        while not self.stopping.wait(wait):
            if not self.p.cfg().get("auto_raise", True) or not self.p.lots.listed():
                wait = 300
                continue
            try:
                with self.fp.lock:
                    sub = self.fp.account.get_subcategory(SubCategoryTypes.COMMON, NODE)
                    self.fp.account.raise_lots(sub.category.id)
                log.info("⬆️ Лоты подняты")
                wait = 4 * 3600
            except exceptions.RaiseError as e:
                wait = max(60, int(e.wait_time or 3600) + 5)
            except Exception as e:
                log.warning("Поднятие лотов: %s", short_error(e))
                wait = 600
