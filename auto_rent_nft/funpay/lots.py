from __future__ import annotations

import re
import threading
import time

from ..config import NODE


def norm(s: str) -> str:
    return re.sub(r"[^a-zа-яё0-9]", "", (s or "").lower())


def fragment_slug(slug: str) -> str:
    base, _, num = (slug or "").rpartition("-")
    return (re.sub(r"[^A-Za-z0-9]", "", base) + "-" + num).lower()


class Lots:
    def __init__(self, plugin):
        self.p = plugin
        self.lock = threading.RLock()
        self._own: tuple[float, list | None] = (0, None)
        self._cols: tuple[float, list] = (0, [])

    @property
    def fp(self):
        return self.p.app.fp

    def collections(self) -> list[dict]:
        ts, cols = self._cols
        if not cols or time.time() - ts > 1800:
            cols = self.p.api.collections()
            self._cols = (time.time(), cols)
        return cols

    def my_lots(self) -> list:
        with self.fp.lock:
            return list(self.fp.account.get_my_subcategory_lots(NODE))

    def own_offers(self) -> list[dict]:
        ts, offers = self._own
        if offers is None or time.time() - ts > 600:
            cols = [{"name": c["name"], "address": c["address"]} for c in self.collections()]
            offers = []
            for lot in self.my_lots():
                text = lot.description or ""
                g = self._best(text, cols)
                if g and re.search(r"аренд|rent", text, re.I):
                    offers.append({**g, "offer_id": int(lot.id), "title": text, "buyer_price": float(lot.price),
                                   "price": float(lot.price), "active": True})
            self._own = (time.time(), offers)
        return offers

    def listed(self) -> list[dict]:
        return self.own_offers()

    def live(self) -> list[dict]:
        gifts = self.listed()
        ts, ids = getattr(self, "_live", (0, None))
        if ids is None or time.time() - ts > 300:
            try:
                ids = {int(x.id) for x in self.my_lots()}
            except Exception:
                ids = None
            self._live = (time.time(), ids)
        if ids is None:
            return gifts
        return [g for g in gifts if not g.get("offer_id") or int(g["offer_id"]) in ids]

    def find(self, text: str, only_listed: bool = True) -> dict | None:
        g = self._best(text, self.own_offers())
        if g or only_listed:
            return g
        return self._best(text, [{"name": c["name"], "address": c["address"]} for c in self.collections()])

    @staticmethod
    def _best(text: str, gifts: list[dict]) -> dict | None:
        t = norm(text)
        best = None
        for g in gifts:
            k = norm(g["name"])
            if k and (k in t or (len(k) > 4 and k.rstrip("s") in t)):
                if not best or len(k) > len(norm(best["name"])):
                    best = g
        return best

    def link(self, g: dict | None) -> str:
        if g and g.get("offer_id"):
            return f"https://funpay.com/lots/offer?id={g['offer_id']}"
        return f"https://funpay.com/lots/{NODE}/"
