from __future__ import annotations

import datetime as dt
import logging
import re
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

import requests

from ..api import ApiError
from ..config import ACTIVE, BIND, MARKER
from . import render
from .bind import CHANNEL_RE, PRIVATE_RE, TC_PIECE_RE, TC_RE, channel_tc, tc_complete

log = logging.getLogger("auto_rent_nft.orders")
MSK = dt.timezone(dt.timedelta(hours=3))
NUM_RE = re.compile(r"(?:№|#)?\s*(\d{1,2})\s*[.)]?")
RENT_WAIT = 480
FAST_WAIT = 900
TARGET_WAIT = 180
COOLDOWN = 20
MAX_FAST = 6
KIND_TITLE = {"me": "👤 Личный аккаунт", "channel": "📢 Каналы", "group": "👥 Группы"}


def until_str(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, MSK).strftime("%d.%m %H:%M")


def days_str(n: int) -> str:
    return "1 сутки" if n == 1 else f"{n} сут."


def term_days(title: str) -> int:
    t = re.sub(r"(?:ОТ|FROM|МИН\.?)\s*\d+\s*\S*", " ", (title or "").upper())
    if m := re.search(r"(\d+)\s*(?:СУТ|ДН|ДЕН|DAY|D\b)", t):
        return max(1, int(m.group(1)))
    if m := re.search(r"(\d+)\s*(?:Ч\b|ЧАС|H\b|HOUR)", t):
        return max(1, -(-int(m.group(1)) // 24))
    if re.search(r"НЕДЕЛ|WEEK", t):
        return 7
    return 1


def left_str(sec: float) -> str:
    sec = max(0, int(sec))
    d, h, m = sec // 86400, sec % 86400 // 3600, sec % 3600 // 60
    return (f"{d} д " if d else "") + (f"{h} ч " if h or d else "") + f"{m} мин"


class Orders:
    def __init__(self, plugin):
        self.p = plugin
        self.picking: set[str] = set()
        self.fast_runs: dict[str, threading.Event] = {}
        self.cool: dict[tuple, float] = {}
        self.img_cache: dict[str, bytes] = {}
        self.watching: set[str] = set()
        self.lock = threading.RLock()

    @property
    def db(self):
        return self.p.store

    @property
    def out(self):
        return self.p.out

    @property
    def T(self):
        return self.p.texts

    @property
    def api(self):
        return self.p.api

    @property
    def lots(self):
        return self.p.lots

    def cfg(self):
        return self.p.cfg()

    def spawn(self, fn, *args):
        def run():
            try:
                fn(*args)
            except Exception:
                log.error("%s упал:\n%s", getattr(fn, "__name__", fn), traceback.format_exc())
        threading.Thread(target=run, name=f"nft-{getattr(fn, '__name__', 'job')}", daemon=True).start()

    def cooldown(self, chat, key) -> bool:
        k = (str(chat), key)
        if time.time() - self.cool.get(k, 0) < COOLDOWN:
            return True
        self.cool[k] = time.time()
        return False

    @staticmethod
    def order_url(oid) -> str:
        return f"https://funpay.com/orders/{oid}/"

    def budget(self, o) -> float:
        s = float(o["sum"] or 0)
        base = max(s * float(self.cfg()["profit_guard"]), s - 1.0)
        test = self.cfg().get("test_gift")
        if test and str(test).lower() == str(o["gift"]).lower():
            return max(base, float(self.cfg().get("test_budget") or 12.0))
        return base

    def on_new_order(self, order) -> bool:
        desc = order.description or ""
        oid = str(order.id)
        if self.db.order(oid):
            return True
        full = self.p.app.fp.get_order(oid)
        body = (getattr(full, "full_description", None) or "") if full else ""
        title = (getattr(full, "short_description", None) or desc) if full else desc
        if MARKER.lower() not in (body + " " + title).lower():
            if full is not None or not self.lots.find(desc):
                return False
            log.warning("Заказ %s: FunPay не открыл страницу заказа, беру по названию лота", oid)
        g = self.lots.find(title) or self.lots.find(body) or self.lots.find(title, only_listed=False) \
            or self.lots.find(body, only_listed=False)
        if not g:
            self.p.alert(f"Заказ #{oid}: в лоте есть {MARKER}, но не понял, какой подарок — «{title[:80]}». "
                         "Напишите в названии лота название подарка как в Telegram (например Plush Pepe)", oid)
            return False
        amount = max(1, int(getattr(full, "amount", None) or getattr(order, "amount", None) or 1))
        days = term_days(title) * amount
        total = float(getattr(full, "sum", None) or order.price or 0)
        chat = getattr(full, "chat_id", None) or order.chat_id
        base = self.active_rental(order.buyer_id or 0, g["address"])
        if base:
            self.db.add(id=oid, chat_id=str(chat), buyer=order.buyer_username or "", buyer_id=order.buyer_id or 0,
                        gift=g["name"], collection=g["address"], days=days, sum=total, state="extending",
                        rental=base["rental"], nft=base["nft"], nft_name=base["nft_name"], slug=base["slug"],
                        turn_at=int(time.time()), note="продление")
            self.db.put(f"ext:{oid}", base["id"])
            log.info("Заказ %s: продление %s на %s сут", oid, base["nft_name"], days)
            self.spawn(self.do_extend, oid, base["id"])
            return True
        self.db.add(id=oid, chat_id=str(chat), buyer=order.buyer_username or "", buyer_id=order.buyer_id or 0,
                    gift=g["name"], collection=g["address"], days=days, sum=total,
                    state="choosing", turn_at=int(time.time()))
        log.info("Заказ %s: %s × %s сут, %s ₽", oid, g["name"], days, order.price)
        self.spawn(self.send_pick, oid, "paid")
        return True

    def on_refund(self, oid) -> None:
        o = self.db.order(oid)
        if not o or o["state"] in ("done", "refunded"):
            return
        before = o["state"] in ("choosing", "paused") or not o["rental"]
        self.stop_fast(oid)
        self.db.upd(oid, state="refunded")
        if not before:
            self.p.alert(f"Возврат по заказу #{oid} уже после аренды {o['nft_name'] or ''} — аренда оплачена", oid)

    def fetch_image(self, slug: str) -> bytes:
        if slug in self.img_cache:
            return self.img_cache[slug]
        from ..funpay.lots import fragment_slug
        try:
            r = requests.get(f"https://nft.fragment.com/gift/{fragment_slug(slug)}.webp", timeout=20,
                             headers={"User-Agent": "Mozilla/5.0"})
            data = r.content if r.ok else b""
        except requests.RequestException:
            data = b""
        if len(self.img_cache) > 600:
            self.img_cache.clear()
        self.img_cache[slug] = data
        return data

    def images(self, snap: list[dict]) -> list[bytes]:
        with ThreadPoolExecutor(8) as ex:
            return list(ex.map(self.fetch_image, [s["slug"] for s in snap]))

    @staticmethod
    def fit_items(items: list[dict], days: int, budget: float, limit: int) -> list[dict]:
        def total(i):
            return i["price_per_day_rub"] * max(int(i.get("min_days") or 1), days)

        fit = [i for i in items if total(i) <= budget]
        fit.sort(key=lambda i: (total(i), i["price_per_day_rub"]))
        return fit[:limit]

    def candidates(self, o) -> tuple[list[dict], str | None]:
        days, budget = max(1, o["days"]), self.budget(o)
        skip = set(o["skip"] or [])
        items = [i for i in self.api.items(o["collection"], limit=100)["items"] if i["nft"] not in skip]
        fit = self.fit_items(items, days, budget, int(self.cfg()["pick_limit"]))
        if fit:
            return fit, None
        cheap = [i for i in items if i["price_per_day_rub"] * days <= budget]
        if cheap:
            self.db.put(f"mindays:{o['id']}", min(int(i.get("min_days") or 1) for i in cheap))
        return [], ("min_days" if cheap else "no_stock")

    def preview_items(self, g: dict) -> list[dict]:
        if g.get("min_days"):
            days = max(1, int(g["min_days"]))
            total = float(g["price"]) * days
        else:
            days = term_days(g.get("title") or "")
            total = float(g["price"])
        budget = max(total * float(self.cfg()["profit_guard"]), total - 1.0)
        items = self.api.items(g["address"], limit=100)["items"]
        return self.fit_items(items, days, budget, int(self.cfg()["pick_limit"]))

    def send_pick(self, oid: str, intro: str = "pick_hint") -> None:
        if oid in self.picking:
            return
        self.picking.add(oid)
        try:
            o = self.db.order(oid)
            if not o or o["state"] not in ("choosing", "paused"):
                return
            try:
                items, why = self.candidates(o)
            except ApiError as e:
                log.warning("Заказ %s: список NFT не получен — %s", oid, e)
                items, why = [], "error"
            if not items:
                if why == "min_days":
                    self.out.text(o["chat_id"], self.T("min_days", gift=o["gift"], min=self.db.get(f"mindays:{oid}") or "?",
                                                       days=o["days"]))
                else:
                    self.out.text(o["chat_id"], self.T("no_stock", gift=o["gift"]))
                self.db.upd(oid, state="failed", note=f"нет подходящих NFT ({why})")
                self.p.alert(f"Заказ #{oid}: нет подходящих {o['gift']} ({why}) — сумма {o['sum']} ₽, {o['days']} сут. "
                             "Выдай вручную или верни деньги", oid)
                return
            snap = [{"nft": i["nft"], "name": i["name"], "slug": i["slug"], "model": i.get("model") or "—",
                     "backdrop": i.get("backdrop") or "—", "symbol": i.get("symbol") or "—",
                     "price": i["price_per_day_rub"], "min_days": int(i.get("min_days") or 1)} for i in items]
            self.db.upd(oid, snapshot=snap, state="choosing", pick=None, turn_at=int(time.time()), reminded=0)
            if intro == "paid":
                self.out.text(o["chat_id"], self.T("paid", gift=o["gift"], days=days_str(o["days"])))
            elif intro in ("pick_taken", "pick_retry"):
                self.out.text(o["chat_id"], self.T(intro))
            imgs = self.images(snap)
            for png in render.pages(imgs, [s["model"] for s in snap]):
                if self.db.order(oid)["state"] != "choosing":
                    return
                self.out.image(o["chat_id"], png)
            self.out.text(o["chat_id"], self.T("pick_hint", n=len(snap)))
        finally:
            self.picking.discard(oid)

    def canon_chat(self, msg) -> str:
        ids = [str(msg.chat_id)]
        author, me = getattr(msg, "author_id", None), self.p.app.fp.my_id
        if author and me:
            a, b = sorted((int(author), int(me)))
            ids.append(f"users-{a}-{b}")
        for cid in ids:
            if self.db.value("SELECT 1 FROM orders WHERE chat_id=? LIMIT 1", cid):
                return cid
        return ids[0]

    def on_message(self, msg) -> bool:
        text = (getattr(msg, "text", None) or "").strip()
        if not text:
            return False
        chat = self.canon_chat(msg)
        low = text.lower()
        words = low.split()
        cmd = words[0] if words else ""
        arg = text.split(maxsplit=1)[1].strip() if len(words) > 1 else ""
        o = self.db.in_chat(chat, ACTIVE)

        if (cmd in ("!нфт", "!nft", "!подарки", "!gifts") and (not arg or arg.isdigit())) or (cmd in ("!модели", "!models") and not arg and not o):
            if not self.cooldown(chat, "nft"):
                self.spawn(self.send_gifts, chat, int(arg) if arg.isdigit() else 1)
            return True
        if cmd in ("!модели", "!models", "!нфт", "!nft", "!подарки"):
            g = self.lots.find(arg) if arg else (self.lots.find(o["gift"]) if o else None)
            if not g:
                self.out.text(chat, self.T("unknown_gift"), once=True)
            elif not self.cooldown(chat, "models:" + g["name"]):
                self.spawn(self.send_models, chat, g)
            return True
        if cmd in ("!помощь", "!команды", "!help"):
            if not self.cooldown(chat, "help"):
                self.out.text(chat, self.T("help"))
            return True
        if cmd in ("!срок", "!мои", "!аренда"):
            if not self.cooldown(chat, "term"):
                self.out.text(chat, self.term(chat))
            return True
        if cmd in ("!продлить", "!продление"):
            done = self.db.in_chat(chat, ("done",))
            g = self.lots.find(done["gift"]) if done else None
            self.out.text(chat, self.T("extend", name=done["nft_name"], link=self.lots.link(g)) if done
                          else self.T("term_none"), once=True)
            return True
        if cmd in ("!привязка", "!bind"):
            if self.cooldown(chat, "bind"):
                return True
            done = self.db.in_chat(chat, ("done",))
            target = o if o and o["state"] in BIND else (done if done and done["until"] > time.time() else None)
            if target:
                self.stop_fast(target["id"])
                self.db.upd(target["id"], state="bind_choice")
                self.out.text(chat, self.T("bind_choice"))
                return True
            return False
        num = NUM_RE.fullmatch(low)
        if num and (not o or o["state"] == "done"):
            seen = self.db.get(f"browse:{chat}")
            if seen and time.time() - seen["ts"] < 900 and 1 <= int(num.group(1)) <= len(seen["names"]):
                g = self.lots.find(seen["names"][int(num.group(1)) - 1])
                if g and not self.cooldown(chat, "models:" + g["name"]):
                    self.spawn(self.send_models, chat, g)
                return True
        if not o:
            return False

        st = o["state"]
        if cmd in ("!модель", "!model"):
            if st in ("choosing", "paused") and not self.cooldown(chat, "pick"):
                self.db.upd(o["id"], state="choosing", reminded=0)
                self.spawn(self.send_pick, o["id"], "pick_hint")
            return True
        if st == "paused":
            if not self.cooldown(chat, "pick"):
                self.db.upd(o["id"], state="choosing", reminded=0)
                self.spawn(self.send_pick, o["id"], "pick_hint")
            return True
        if st == "choosing" and num:
            self.choose(o, int(num.group(1)))
            return True
        if st in ("bind_choice", "bind_manual") and low in ("1", "1.", "быстро", "быстрый"):
            self.start_fast(o["id"])
            return True
        if st in ("bind_choice", "bind_fast") and low in ("2", "2.", "вручную", "ручной"):
            self.stop_fast(o["id"])
            self.db.upd(o["id"], state="bind_manual")
            self.out.text(chat, self.T("bind_manual"))
            return True
        if st == "bind_target" and num:
            self.pick_target(o, int(num.group(1)))
            return True
        if st in BIND and self.on_bind_link(o, text):
            return True
        if st == "bind_manual" and len(low) > 20 and ("ton" in low or "://" in low):
            self.out.text(chat, self.T("not_tc"), once=True)
            return True
        if st in ("choosing", "renting", "extending") + BIND:
            return True
        return False

    def choose(self, o, n: int) -> None:
        snap = o["snapshot"] or []
        if not 1 <= n <= len(snap):
            self.out.text(o["chat_id"], self.T("bad_number", n=len(snap)), once=True)
            return
        if not self.db.swap(o["id"], ("choosing",), "renting", pick=n):
            return
        it = snap[n - 1]
        self.out.text(o["chat_id"], self.T("chosen", n=n, name=it["name"], model=it["model"], backdrop=it["backdrop"]))
        self.spawn(self.do_rent, o["id"])

    def do_rent(self, oid: str) -> None:
        o = self.db.order(oid)
        it = o["snapshot"][o["pick"] - 1]
        days = max(int(it["min_days"]), int(o["days"]))
        try:
            rate = self.api.price(it["nft"], days)
        except ApiError as e:
            log.warning("Заказ %s: цена %s не получена — %s", oid, it["name"], e)
            return self.taken(oid, None, "pick_retry")
        if not rate.get("available"):
            return self.taken(oid, it["nft"])
        days = max(days, int(rate.get("days") or days))
        total = float(rate.get("total_rub") or 0)
        if total > self.budget(o):
            self.db.upd(oid, state="failed", note=f"убыточно: {total} ₽ при заказе {o['sum']} ₽")
            self.out.text(o["chat_id"], self.T("seller"))
            return self.p.alert(f"Заказ #{oid}: аренда {it['name']} стоит {total:.2f} ₽, заказ {o['sum']} ₽ — не арендую", oid)
        started = int(time.time())
        r, err = None, None
        try:
            r = self.api.rent(it["nft"], days)
        except ApiError as e:
            err = e
            if e.code == "network":
                r = self.find_rental(it["nft"], started)
                if r is not None:
                    log.warning("Заказ %s: ответ на аренду не пришёл, но аренда %s уже оформлена", oid, r.get("order_id"))
        if r is None:
            if err.code == "not_available":
                return self.taken(oid, it["nft"])
            if err.code == "insufficient_balance":
                self.db.upd(oid, state="failed", note="мало денег на балансе API")
                self.out.text(o["chat_id"], self.T("seller"))
                return self.p.alert(f"Заказ #{oid}: на балансе API не хватает {total:.2f} ₽ — пополни "
                                    "(@BlimyStarsBot → Профиль → API) и нажми «Повторить» в меню плагина", oid)
            self.db.upd(oid, state="failed", note=f"аренда: {err}")
            self.out.text(o["chat_id"], self.T("seller"))
            return self.p.alert(f"Заказ #{oid}: аренда {it['name']} не оформилась — {err}. Проверь в «Аренды»", oid)
        self.db.upd(oid, rental=r["order_id"], cost=float(r.get("total_rub") or total), nft=it["nft"],
                    nft_name=it["name"], slug=it["slug"])
        log.info("Заказ %s: аренда %s (%s) на %s сут за %s ₽", oid, r["order_id"], it["name"], days, r.get("total_rub"))
        self.watch_rent(oid, RENT_WAIT)

    def find_rental(self, nft: str, since: float) -> dict | None:
        try:
            rows = self.api.orders("rent_nft", 20)
        except ApiError:
            return None
        for r in rows:
            if r.get("nft") == nft and r.get("status") not in ("refunded", "canceled") \
                    and int(r.get("created") or 0) >= since - 120:
                return r
        return None

    def watch_rent(self, oid: str, timeout: float) -> None:
        o = self.db.order(oid)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                info = self.api.order(o["rental"])
            except ApiError as e:
                log.warning("Заказ %s: статус %s — %s", oid, o["rental"], e)
                time.sleep(6)
                continue
            status = info.get("status")
            if status in ("awaiting_connect", "binding", "completed"):
                return self.rented(oid, info)
            if status in ("refunded", "canceled"):
                if not self.db.swap(oid, ("renting",), "choosing", rental=None, cost=0):
                    return
                log.info("Заказ %s: аренду %s отменили (%s) — новый выбор", oid, o["rental"], status)
                return self.taken(oid, o["nft"])
            time.sleep(4)
        if self.db.order(oid)["state"] == "renting" and not self.db.get(f"delay:{oid}"):
            self.db.put(f"delay:{oid}", 1)
            self.out.text(o["chat_id"], self.T("delay"))
            self.p.alert(f"Заказ #{oid}: аренда {o['rental']} подтверждается дольше {int(timeout // 60)} мин — слежу дальше", oid)

    def rented(self, oid: str, info: dict) -> None:
        o = self.db.order(oid)
        until = int(info.get("until") or time.time() + max(1, o["days"]) * 86400)
        if not self.db.swap(oid, ("renting",), "bind_choice", until=until):
            return
        self.out.text(o["chat_id"], self.T("rented", name=o["nft_name"], until=until_str(until)))

    def taken(self, oid: str, nft: str | None, intro: str = "pick_taken") -> None:
        o = self.db.order(oid)
        skip = sorted(set(o["skip"] or []) | ({nft} if nft else set()))
        self.db.upd(oid, state="choosing", pick=None, snapshot=None, skip=skip, turn_at=int(time.time()), reminded=0)
        self.send_pick(oid, intro)

    def on_bind_link(self, o, text: str) -> bool:
        oid, chat = o["id"], o["chat_id"]
        if PRIVATE_RE.search(text):
            self.out.text(chat, self.T("channel_private"), once=True)
            return True
        compact = re.sub(r"\s+", "", text)
        part = self.db.get(f"tcpart:{oid}")
        m = TC_RE.search(compact)
        if m:
            link = m.group(0)
        elif part and TC_PIECE_RE.fullmatch(compact):
            link = part + compact
        else:
            ch = CHANNEL_RE.search(text.strip())
            if not ch:
                return False
            self.db.put(f"tcpart:{oid}", None)
            self.spawn(self.do_channel, oid, ch.group(1) or ch.group(2))
            return True
        if not tc_complete(link):
            self.db.put(f"tcpart:{oid}", link)
            if m:
                self.out.text(chat, self.T("tc_cut"), once=True)
            return True
        self.db.put(f"tcpart:{oid}", None)
        self.start_manual(oid, link)
        return True

    def start_manual(self, oid: str, link: str) -> None:
        if not self.db.swap(oid, BIND, "bind_manual"):
            return
        self.stop_fast(oid)
        self.spawn(self.do_connect, oid, link)

    def do_channel(self, oid: str, name: str) -> None:
        o = self.db.order(oid)
        self.out.text(o["chat_id"], self.T("channel_looking"))
        link, seen = None, False
        for _ in range(3):
            try:
                link, seen = channel_tc(name)
            except Exception as e:
                log.warning("Канал %s (заказ %s): %s", name, oid, e)
            if link:
                break
            time.sleep(5)
        if not link:
            self.out.text(o["chat_id"], self.T("channel_cut" if seen else "channel_empty"))
            return
        self.start_manual(oid, link)

    def do_connect(self, oid: str, link: str) -> None:
        o = self.db.order(oid)
        self.out.text(o["chat_id"], self.T("bind_working"))
        try:
            self.api.connect(o["rental"], link)
        except ApiError as e:
            log.warning("Заказ %s: connect — %s", oid, e)
            self.out.text(o["chat_id"], self.T("bind_failed"))
            return
        self.done(oid, "manual")

    def start_fast(self, oid: str) -> None:
        runs = int(self.db.get(f"fastruns:{oid}") or 0)
        if runs >= MAX_FAST:
            o = self.db.order(oid)
            if o and o["state"] in ("bind_choice", "bind_manual"):
                self.db.upd(oid, state="bind_manual")
                self.out.text(o["chat_id"], self.T("fast_limit"), once=True)
            return
        if not self.db.swap(oid, ("bind_choice", "bind_manual"), "bind_fast"):
            return
        self.db.put(f"fastruns:{oid}", runs + 1)
        self.spawn(self.fast_run, oid)

    def stop_fast(self, oid: str) -> None:
        ev = self.fast_runs.pop(oid, None)
        if ev:
            ev.set()
            o = self.db.order(oid)
            if o and o["rental"]:
                self.spawn(self._cancel_fast, o["rental"])

    def _cancel_fast(self, rental: str) -> None:
        try:
            self.api.fast_cancel(rental)
        except ApiError:
            pass

    def to_manual(self, oid: str, why: str) -> None:
        o = self.db.order(oid)
        self.db.upd(oid, state="bind_manual")
        self.out.text(o["chat_id"], self.T("fast_to_manual"))
        self.p.alert(f"Заказ #{oid}: быстрая привязка не удалась ({why}) — покупатель на ручной", oid, kind="errors")

    def fast_run(self, oid: str) -> None:
        o = self.db.order(oid)
        stop = threading.Event()
        old = self.fast_runs.pop(oid, None)
        if old:
            old.set()
        self.fast_runs[oid] = stop
        try:
            try:
                st = self.api.fast_start(o["rental"])
            except ApiError as e:
                return self.to_manual(oid, str(e))
            if st.get("stage") in ("failed", "expired") or not st.get("login_url"):
                return self.to_manual(oid, st.get("error") or st.get("stage") or "нет ссылки")
            pc = st.get("desktop_url") or st["login_url"]
            self.out.text(o["chat_id"], self.T("fast_link", link=st["login_url"], pc=pc))
            code_sent, targets_sent = None, False
            target_deadline, auto_done, silent = None, False, False
            deadline = time.time() + FAST_WAIT
            while time.time() < deadline and not stop.wait(4):
                try:
                    st = self.api.fast_status(o["rental"])
                except ApiError as e:
                    log.warning("Заказ %s: статус привязки — %s", oid, e)
                    continue
                stage = st.get("stage")
                if st.get("match_code") and st["match_code"] != code_sent:
                    code_sent = st["match_code"]
                    self.out.text(o["chat_id"], self.T("fast_code", code=code_sent))
                if stage == "choose_target" and not targets_sent:
                    targets = st.get("targets") or []
                    targets_sent = True
                    if st.get("telegram_user"):
                        self.db.upd(oid, tg=st["telegram_user"])
                    if targets and all(t.get("kind", "me") == "me" for t in targets) and self.auto_target(o["rental"], targets):
                        auto_done = silent = True
                        continue
                    lines, kind = [], None
                    for i, t in enumerate(targets, 1):
                        if t.get("kind", "me") != kind:
                            kind = t.get("kind", "me")
                            lines.append(("\n" if lines else "") + KIND_TITLE.get(kind, "📌 Другое"))
                        lines.append(f"{i}. {t['name']}")
                    self.db.put(f"targets:{oid}", targets)
                    self.db.upd(oid, state="bind_target")
                    self.out.text(o["chat_id"], self.T("fast_targets", lines="\n".join(lines)))
                    target_deadline = time.time() + TARGET_WAIT
                    deadline = max(deadline, target_deadline + 120)
                elif stage == "choose_target" and target_deadline and not auto_done and time.time() >= target_deadline:
                    if self.db.swap(oid, ("bind_target",), "bind_fast"):
                        if self.auto_target(o["rental"], self.db.get(f"targets:{oid}") or []):
                            self.out.text(o["chat_id"], self.T("fast_auto"))
                            auto_done = True
                        else:
                            self.db.upd(oid, state="bind_target")
                            target_deadline = time.time() + 30
                    else:
                        auto_done = True
                elif stage == "completed":
                    if st.get("telegram_user"):
                        self.db.upd(oid, tg=st["telegram_user"])
                    return self.done(oid, "fast_auto" if silent else "fast", st.get("target"))
                elif stage == "failed":
                    return self.to_manual(oid, st.get("error") or "ошибка")
                elif stage in ("expired", "canceled"):
                    if not stop.is_set():
                        self.db.upd(oid, state="bind_choice")
                        self.out.text(o["chat_id"], self.T("fast_expired"))
                    return
            if not stop.is_set():
                self._cancel_fast(o["rental"])
                self.db.upd(oid, state="bind_choice")
                self.out.text(o["chat_id"], self.T("fast_expired"))
        finally:
            if self.fast_runs.get(oid) is stop:
                self.fast_runs.pop(oid, None)

    def auto_target(self, rental: str, targets: list) -> bool:
        if not targets:
            return False
        mine = next((t for t in targets if t.get("kind", "me") == "me"), targets[0])
        try:
            self.api.fast_target(rental, int(mine.get("index", 0)))
            return True
        except ApiError as e:
            log.warning("Аренда %s: автоматический выбор места — %s", rental, e)
            return False

    def pick_target(self, o, n: int) -> None:
        targets = self.db.get(f"targets:{o['id']}") or []
        if not 1 <= n <= len(targets):
            self.out.text(o["chat_id"], self.T("bad_number", n=len(targets)), once=True)
            return
        try:
            self.api.fast_target(o["rental"], int(targets[n - 1].get("index", n - 1)))
            self.db.swap(o["id"], ("bind_target",), "bind_fast")
        except ApiError as e:
            log.warning("Заказ %s: выбор цели — %s", o["id"], e)
            self.out.text(o["chat_id"], self.T("fast_expired"))
            self.db.upd(o["id"], state="bind_choice")

    def done(self, oid: str, how: str, target: str | None = None) -> None:
        o = self.db.order(oid)
        if o["state"] == "done":
            return
        self.db.upd(oid, state="done")
        self.db.put(f"targets:{oid}", None)
        if how in ("fast", "fast_auto"):
            where = "в вашем профиле" if not target or target in ("Мой профиль",) or (o["tg"] or {}).get("name") == target \
                else f"в «{target}»"
            text = self.T("done_auto" if how == "fast_auto" else "done_fast", name=o["nft_name"], target=where,
                          until=until_str(o["until"]))
        else:
            text = self.T("done_manual", until=until_str(o["until"]))
        self.out.text(o["chat_id"], text + "\n\n" + self.T("ask_review", order_url=self.order_url(oid)))
        self.p.delivered(self.db.order(oid), "fast" if how.startswith("fast") else how)

    def tick(self) -> None:
        now = time.time()
        c = self.cfg()
        for o in self.db.by_state("choosing"):
            idle = now - max(o["turn_at"] or 0, o["updated"] or 0)
            if idle > float(c["pause_after"]):
                self.db.upd(o["id"], state="paused", snapshot=None)
                self.out.text(o["chat_id"], self.T("paused"))
            elif idle > float(c["remind_after"]) and not o["reminded"] and o["snapshot"]:
                self.db.upd(o["id"], reminded=1)
                self.out.text(o["chat_id"], self.T("remind"))
        for o in self.db.by_state("renting"):
            if o["rental"] and now - (o["updated"] or 0) > 60 and o["id"] not in self.watching:
                self.watching.add(o["id"])
                self.spawn(self._watch_once, o["id"])
        for o in self.db.rows("SELECT * FROM orders WHERE state='done' AND until>?", now - 6 * 3600):
            if o["until"] > now and o["until"] - now < float(c["end_remind"]) and not o["end_reminded"]:
                self.db.upd(o["id"], end_reminded=1)
                self.out.text(o["chat_id"], self.T("end_soon", name=o["nft_name"], until=until_str(o["until"])))
            elif o["until"] <= now and not o["ended"]:
                self.db.upd(o["id"], ended=1)
                g = self.lots.find(o["gift"])
                self.out.text(o["chat_id"], self.T("ended", name=o["nft_name"], link=self.lots.link(g)))

    def _watch_once(self, oid: str) -> None:
        try:
            self.watch_rent(oid, 30)
        finally:
            self.watching.discard(oid)

    def recover(self) -> None:
        for o in self.db.by_state("extending"):
            self.db.upd(o["id"], state="failed", note="продление прервано перезапуском, проверьте аренду")
            self.p.alert(f"Заказ #{o['id']}: продление прервалось при перезапуске. Проверь аренду и нажми «Повторить», "
                         "только если срок не продлён", o["id"])
        for o in self.db.by_state("bind_fast", "bind_target"):
            self.db.upd(o["id"], state="bind_choice")
            self.out.text(o["chat_id"], self.T("fast_expired"))
        for o in self.db.by_state("renting"):
            if o["rental"]:
                continue
            snap, pick = o["snapshot"] or [], o["pick"] or 0
            nft = snap[pick - 1]["nft"] if 1 <= pick <= len(snap) else None
            r = self.find_rental(nft, o["updated"] or 0) if nft else None
            if r:
                self.db.upd(o["id"], rental=r["order_id"], cost=float(r.get("total_rub") or 0), nft=nft,
                            nft_name=r.get("name") or "", slug=r.get("slug") or "")
                self.spawn(self.watch_rent, o["id"], RENT_WAIT)
            else:
                self.db.upd(o["id"], state="choosing", pick=None, snapshot=None)
                self.spawn(self.send_pick, o["id"], "pick_retry")
        for o in self.db.by_state("choosing"):
            if not o["snapshot"]:
                self.spawn(self.send_pick, o["id"], "paid")

    def active_rental(self, buyer_id: int, collection: str) -> dict | None:
        if not buyer_id:
            return None
        rows = self.db.rows("SELECT * FROM orders WHERE buyer_id=? AND collection=? AND state='done' AND until>? "
                            "AND COALESCE(rental,'')!='' AND COALESCE(note,'')!='продление' ORDER BY until DESC LIMIT 1",
                            buyer_id, collection, time.time() + 120)
        return rows[0] if rows else None

    def do_extend(self, oid: str, base_id) -> None:
        o, base = self.db.order(oid), self.db.order(base_id)
        if not o or not base or o["state"] != "extending":
            return
        self.out.text(o["chat_id"], self.T("extending", name=base["nft_name"], days=days_str(o["days"])))
        try:
            r = self.api.extend(base["rental"], o["days"], self.budget(o))
        except ApiError as e:
            return self.extend_failed(oid, e)
        until = int(r.get("until") or (base["until"] + o["days"] * 86400))
        cost = float(r.get("total_rub") or 0)
        self.db.upd(base_id, until=until, end_reminded=0, ended=0, reminded=0)
        self.db.upd(oid, state="done", until=until, cost=cost, ended=1, end_reminded=1, note="продление")
        self.out.text(o["chat_id"], self.T("extended", name=base["nft_name"], days=days_str(o["days"]), until=until_str(until))
                      + "\n\n" + self.T("ask_review", order_url=self.order_url(oid)))
        self.p.extended(self.db.order(oid), o["days"])

    def extend_failed(self, oid: str, e: ApiError) -> None:
        o = self.db.order(oid)
        log.warning("Заказ %s: продление — %s", oid, e)
        self.db.upd(oid, state="failed", note=f"продление: {e}")
        if e.code in ("not_extendable", "bad_state", "too_long"):
            self.out.text(o["chat_id"], self.T("extend_na"))
        else:
            self.out.text(o["chat_id"], self.T("seller"))
        if e.code == "insufficient_balance":
            self.p.alert(f"Заказ #{oid}: на балансе API не хватает денег на продление — пополни и нажми «Повторить»", oid)
        else:
            self.p.alert(f"Заказ #{oid}: продление не вышло — {e}. Разберись с покупателем или верни деньги", oid)

    def fetch_url(self, url: str) -> bytes:
        if not url:
            return b""
        if url in self.img_cache:
            return self.img_cache[url]
        try:
            r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            data = r.content if r.ok else b""
        except requests.RequestException:
            data = b""
        if len(self.img_cache) > 600:
            self.img_cache.clear()
        self.img_cache[url] = data
        return data

    def send_gifts(self, chat: str, page: int = 1) -> None:
        gifts = sorted((g for g in self.lots.live() if g.get("active", True)), key=lambda g: g["price"])
        if not gifts:
            self.out.text(chat, self.T("nft_empty"))
            return
        try:
            covers = {c["address"]: c.get("image") for c in self.lots.collections()}
        except ApiError:
            covers = {}
        with ThreadPoolExecutor(8) as ex:
            imgs = list(ex.map(self.fetch_url, [covers.get(g["address"]) for g in gifts]))
        labels = [g["name"] for g in gifts]
        badges = [f"{g['price']:.2f}".rstrip("0").rstrip(".") + " ₽" for g in gifts]
        self.db.put(f"browse:{chat}", {"names": labels, "ts": time.time()})
        per = 12
        for i in range(0, len(gifts), per):
            self.out.image(chat, render.grid(imgs[i:i + per], labels[i:i + per], start=i + 1, badges=badges[i:i + per]))
        self.out.text(chat, self.T("gifts_hint", n=len(gifts), more=""))

    def send_models(self, chat: str, g: dict) -> None:
        try:
            items = self.preview_items(g)
        except ApiError:
            items = []
        if not items:
            self.out.text(chat, self.T("no_stock", gift=g["name"]))
            return
        imgs = self.images([{"slug": i["slug"]} for i in items])
        for png in render.pages(imgs, [i.get("model") or "—" for i in items]):
            self.out.image(chat, png)
        self.out.text(chat, self.T("models_caption", gift=g["name"], link=self.lots.link(g)))

    def term(self, chat: str) -> str:
        now = time.time()
        rows = self.db.rows("SELECT * FROM orders WHERE chat_id=? AND state='done' AND until>? AND COALESCE(note,'')!='продление' "
                            "ORDER BY until",
                            str(chat), now)
        if not rows:
            return self.T("term_none")
        return "\n".join(self.T("term", name=o["nft_name"], until=until_str(o["until"]), left=left_str(o["until"] - now))
                         for o in rows)

    def retry(self, oid: str) -> bool:
        o = self.db.order(oid)
        if not o or o["state"] not in ("failed", "paused", "choosing"):
            return False
        base_id = self.db.get(f"ext:{oid}")
        if base_id:
            self.db.upd(oid, state="extending", note="продление")
            self.spawn(self.do_extend, oid, base_id)
            return True
        if o["rental"]:
            self.db.upd(oid, state="renting", note="")
            self.spawn(self.watch_rent, oid, 60)
        else:
            self.db.upd(oid, state="choosing", note="", snapshot=None, pick=None)
            self.spawn(self.send_pick, oid, "pick_retry")
        return True
