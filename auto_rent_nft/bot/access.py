from __future__ import annotations

import hmac
import json
import threading
import time
from pathlib import Path

MAX_TRIES = 5
LOCK_SEC = 600


class Access:
    def __init__(self, path: Path, password: str = "", preset: list[int] | None = None):
        self.path = path
        self.password = password
        self.lock = threading.RLock()
        self.admins: list[int] = []
        self.tries: dict[int, list[float]] = {}
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = []
        for uid in [*(preset or []), *saved]:
            if int(uid) not in self.admins:
                self.admins.append(int(uid))

    @property
    def open(self) -> bool:
        return bool(self.password) or bool(self.admins)

    def allowed(self, uid: int) -> bool:
        return uid in self.admins

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.admins), encoding="utf-8")
        tmp.replace(self.path)

    def login(self, uid: int, text: str) -> str:
        with self.lock:
            if uid in self.admins:
                return "ok"
            if not self.password:
                return "nopass"
            now = time.time()
            recent = [t for t in self.tries.get(uid, []) if now - t < LOCK_SEC]
            if len(recent) >= MAX_TRIES:
                self.tries[uid] = recent
                return "locked"
            if hmac.compare_digest(text.strip().encode(), self.password.encode()):
                self.tries.pop(uid, None)
                self.admins.append(uid)
                self._save()
                return "ok"
            recent.append(now)
            self.tries[uid] = recent
            return "locked" if len(recent) >= MAX_TRIES else "bad"

    def left(self, uid: int) -> int:
        now = time.time()
        return max(0, MAX_TRIES - len([t for t in self.tries.get(uid, []) if now - t < LOCK_SEC]))
