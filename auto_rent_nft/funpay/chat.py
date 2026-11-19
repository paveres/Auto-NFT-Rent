from __future__ import annotations

import logging
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("auto_rent_nft.chat")
GAP = 2.0
MAX_LEN, MAX_LINES = 900, 14
DEDUP_SEC = 90
FLOOD_MAX, FLOOD_SEC = 14, 60


def split(text: str) -> list[str]:
    parts, cur = [], ""
    for line in text.split("\n"):
        while len(line) > MAX_LEN:
            parts.append(line[:MAX_LEN])
            line = line[MAX_LEN:]
        if cur and (len(cur) + len(line) + 1 > MAX_LEN or cur.count("\n") >= MAX_LINES - 1):
            parts.append(cur.rstrip("\n"))
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur.rstrip("\n"))
    return [p for p in parts if p.strip()]


class Outbox:
    def __init__(self, fp, on_fail=None, on_flood=None):
        self.fp = fp
        self.on_fail = on_fail
        self.on_flood = on_flood
        self.recent: dict[str, deque] = {}
        self.flood_at: dict[str, float] = {}
        self.q: dict[str, deque] = {}
        self.last_at: dict[str, float] = {}
        self.last_text: dict[str, str] = {}
        self.busy: set[str] = set()
        self.cv = threading.Condition()
        self.pool = ThreadPoolExecutor(8, thread_name_prefix="nft-send")
        self.stopped = False
        threading.Thread(target=self._run, name="nft-outbox", daemon=True).start()

    def text(self, chat_id, text: str, once: bool = False) -> None:
        chat = str(chat_id)
        if not text:
            return
        now = time.time()
        key = " ".join(text.split())
        with self.cv:
            seen = self.recent.setdefault(chat, deque())
            while seen and now - seen[0][0] > max(DEDUP_SEC, FLOOD_SEC):
                seen.popleft()
            if any(k == key and now - t < DEDUP_SEC for t, k in seen):
                return
            if sum(1 for t, _ in seen if now - t < FLOOD_SEC) >= FLOOD_MAX:
                if self.on_flood and now - self.flood_at.get(chat, 0) > 300:
                    self.flood_at[chat] = now
                    threading.Thread(target=self.on_flood, args=(chat,), daemon=True).start()
                return
            seen.append((now, key))
            items = self.q.setdefault(chat, deque())
            if once and self.last_text.get(chat) == text and not items:
                return
            if items and items[-1][0] == "text":
                if items[-1][1] != text:
                    items[-1] = ("text", items[-1][1] + "\n\n" + text)
            else:
                items.append(("text", text))
            self.cv.notify()

    def image(self, chat_id, png: bytes) -> None:
        with self.cv:
            self.q.setdefault(str(chat_id), deque()).append(("image", png))
            self.cv.notify()

    def _run(self) -> None:
        while not self.stopped:
            with self.cv:
                now = time.time()
                ready = [c for c, it in self.q.items() if it and c not in self.busy and now - self.last_at.get(c, 0) >= GAP]
                if not ready:
                    self.cv.wait(0.3)
                    continue
                for chat in ready:
                    kind, val = self.q[chat].popleft()
                    self.busy.add(chat)
                    self.pool.submit(self._send, chat, kind, val)

    def _send(self, chat: str, kind: str, val) -> None:
        try:
            for attempt in range(3):
                try:
                    if kind == "text":
                        for part in split(val):
                            if not self.fp.send(chat, part):
                                raise RuntimeError("FunPay не принял сообщение")
                        self.last_text[chat] = val
                    else:
                        with self.fp.lock:
                            self.fp.account.send_image(int(chat) if chat.isdigit() else chat, val)
                    break
                except Exception as e:
                    log.warning("В чат %s не ушло (%s/3): %s", chat, attempt + 1, e)
                    time.sleep(3 * (attempt + 1))
            else:
                log.error("В чат %s сообщение не доставлено", chat)
                if self.on_fail:
                    try:
                        self.on_fail(chat, kind, val if kind == "text" else "")
                    except Exception:
                        log.exception("on_fail")
        finally:
            with self.cv:
                self.busy.discard(chat)
                self.last_at[chat] = time.time()
                self.cv.notify()

    def stop(self) -> None:
        self.stopped = True
