from __future__ import annotations

import logging
import threading
import time
import urllib.parse

import requests

log = logging.getLogger("auto_rent_nft.api")


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 0, data: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.data = code, message, status, data or {}

    def __str__(self):
        return f"{self.code}: {self.message}"


class StarShopAPI:
    def __init__(self, cfg):
        self.cfg = cfg
        self.http = requests.Session()
        self.lock = threading.Lock()
        self.gap = 1.0
        self._last = 0.0

    @property
    def ready(self) -> bool:
        c = self.cfg()
        return bool(c.get("api_token") and c.get("api_pin"))

    def _req(self, method: str, path: str, params: dict | None = None, body: dict | None = None,
             timeout: float = 30, attempts: int = 6) -> dict:
        c = self.cfg()
        if not self.ready:
            raise ApiError("no_key", "Ключ API не задан — меню плагина → 🔑 Ключ API")
        url = c["api_url"].rstrip("/") + path
        headers = {"Authorization": "Bearer " + c["api_token"], "X-Api-Pin": str(c["api_pin"]),
                   "User-Agent": "nft-rent-funpay/1.0"}
        data = {}
        for attempt in range(attempts):
            with self.lock:
                wait = self.gap - (time.time() - self._last)
                if wait > 0:
                    time.sleep(wait)
                try:
                    r = self.http.request(method, url, params=params, json=body, headers=headers, timeout=timeout)
                except requests.RequestException as e:
                    self._last = time.time()
                    if attempt + 1 >= attempts or method != "GET":
                        raise ApiError("network", f"Сервис не отвечает: {e}") from e
                    time.sleep(2 + attempt * 2)
                    continue
                self._last = time.time()
            try:
                data = r.json()
            except ValueError:
                data = {"success": False, "error": "bad_response", "message": r.text[:200]}
            if r.status_code == 429 and data.get("error") == "rate_limited" and attempt + 1 < attempts:
                time.sleep(float(data.get("retry_after") or 1) + 0.3)
                continue
            if r.status_code >= 500 and method == "GET" and attempt + 1 < attempts:
                time.sleep(2 + attempt * 2)
                continue
            break
        if not data.get("success"):
            raise ApiError(str(data.get("error") or "error"), str(data.get("message") or data), r.status_code, data)
        return data

    def me(self) -> dict:
        d = self._req("GET", "/me")
        gap = float((d.get("limits") or {}).get("min_interval_sec") or self.gap)
        self.gap = max(0.3, gap)
        return d

    def balance(self) -> float:
        return float(self.me()["client"]["balance_rub"])

    def collections(self) -> list[dict]:
        return self._req("GET", "/nft/collections")["collections"]

    def items(self, collection: str, limit: int = 100, cursor: int = 0) -> dict:
        return self._req("GET", "/nft/items", {"collection": collection, "limit": limit, "cursor": cursor})

    def price(self, nft: str, days: int) -> dict:
        return self._req("GET", f"/nft/items/{urllib.parse.quote(nft, safe='')}/price", {"days": days})

    def rent(self, nft: str, days: int) -> dict:
        return self._req("POST", "/nft/rentals", body={"nft": nft, "days": days}, timeout=60, attempts=1)

    def order(self, order_id: str) -> dict:
        return self._req("GET", f"/orders/{order_id}")["order"]

    def extend(self, order_id: str, days: int, max_rub: float | None = None) -> dict:
        body = {"days": int(days)}
        if max_rub is not None:
            body["max_rub"] = round(float(max_rub), 2)
        return self._req("POST", f"/nft/rentals/{order_id}/extend", body=body, timeout=260, attempts=1)

    def orders(self, kind: str = "", limit: int = 20) -> list[dict]:
        return self._req("GET", "/orders", {"type": kind, "limit": limit})["orders"]

    def connect(self, order_id: str, tonconnect_url: str) -> dict:
        return self._req("POST", f"/nft/rentals/{order_id}/connect", body={"tonconnect_url": tonconnect_url},
                         timeout=200, attempts=1)

    def fast_start(self, order_id: str) -> dict:
        return self._req("POST", f"/nft/rentals/{order_id}/telegram", timeout=40, attempts=1)

    def fast_status(self, order_id: str) -> dict:
        return self._req("GET", f"/nft/rentals/{order_id}/telegram")

    def fast_target(self, order_id: str, index: int) -> dict:
        return self._req("POST", f"/nft/rentals/{order_id}/telegram/target", body={"target": index}, attempts=1)

    def fast_cancel(self, order_id: str) -> dict:
        return self._req("POST", f"/nft/rentals/{order_id}/telegram/cancel", attempts=2)
