from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders(
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    buyer TEXT DEFAULT '',
    buyer_id INTEGER DEFAULT 0,
    gift TEXT DEFAULT '',
    collection TEXT DEFAULT '',
    days INTEGER NOT NULL DEFAULT 1,
    sum REAL NOT NULL DEFAULT 0,
    state TEXT NOT NULL,
    snapshot TEXT,
    skip TEXT,
    pick INTEGER,
    rental TEXT,
    nft TEXT, nft_name TEXT, slug TEXT,
    cost REAL NOT NULL DEFAULT 0,
    until INTEGER NOT NULL DEFAULT 0,
    note TEXT DEFAULT '',
    tg TEXT,
    turn_at INTEGER NOT NULL DEFAULT 0,
    reminded INTEGER NOT NULL DEFAULT 0,
    end_reminded INTEGER NOT NULL DEFAULT 0,
    ended INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL,
    updated INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_state ON orders(state);
CREATE INDEX IF NOT EXISTS orders_chat ON orders(chat_id);
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
"""
JSON_COLS = ("snapshot", "skip", "tg")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript(SCHEMA)

    @staticmethod
    def _row(r) -> dict | None:
        if r is None:
            return None
        d = dict(r)
        for k in JSON_COLS:
            d[k] = json.loads(d[k]) if d.get(k) else None
        return d

    def order(self, oid: str) -> dict | None:
        with self.lock:
            return self._row(self.db.execute("SELECT * FROM orders WHERE id=?", (str(oid),)).fetchone())

    def add(self, **f) -> None:
        now = int(time.time())
        f.setdefault("created", now)
        f["updated"] = now
        for k in JSON_COLS:
            if k in f and f[k] is not None:
                f[k] = json.dumps(f[k], ensure_ascii=False)
        cols = ",".join(f)
        with self.lock:
            self.db.execute(f"INSERT OR IGNORE INTO orders({cols}) VALUES({','.join('?' * len(f))})", tuple(f.values()))

    def upd(self, oid: str, **f) -> None:
        f["updated"] = int(time.time())
        for k in JSON_COLS:
            if k in f and f[k] is not None:
                f[k] = json.dumps(f[k], ensure_ascii=False)
        sets = ",".join(f"{k}=?" for k in f)
        with self.lock:
            self.db.execute(f"UPDATE orders SET {sets} WHERE id=?", (*f.values(), str(oid)))

    def swap(self, oid: str, old: tuple, new: str, **f) -> bool:
        with self.lock:
            o = self.order(oid)
            if not o or o["state"] not in old:
                return False
            self.upd(oid, state=new, **f)
            return True

    def by_state(self, *states) -> list[dict]:
        with self.lock:
            rows = self.db.execute(f"SELECT * FROM orders WHERE state IN ({','.join('?' * len(states))}) "
                                   "ORDER BY created", states).fetchall()
        return [self._row(r) for r in rows]

    def in_chat(self, chat_id, states) -> dict | None:
        with self.lock:
            r = self.db.execute(f"SELECT * FROM orders WHERE chat_id=? AND state IN ({','.join('?' * len(states))}) "
                                "ORDER BY created DESC LIMIT 1", (str(chat_id), *states)).fetchone()
        return self._row(r)

    def rows(self, sql: str, *args) -> list[dict]:
        with self.lock:
            return [self._row(r) for r in self.db.execute(sql, args).fetchall()]

    def value(self, sql: str, *args):
        with self.lock:
            r = self.db.execute(sql, args).fetchone()
        return r[0] if r else None

    def get(self, k: str, default=None):
        with self.lock:
            r = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else default

    def put(self, k: str, v) -> None:
        with self.lock:
            if v is None:
                self.db.execute("DELETE FROM kv WHERE k=?", (k,))
            else:
                self.db.execute("INSERT OR REPLACE INTO kv(k, v) VALUES(?, ?)", (k, json.dumps(v, ensure_ascii=False)))
