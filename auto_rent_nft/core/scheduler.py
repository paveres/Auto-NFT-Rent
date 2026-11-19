from __future__ import annotations

import logging
import threading
import traceback

log = logging.getLogger("auto_rent_nft.scheduler")
TICK = 30


class Scheduler:
    def __init__(self, plugin):
        self.p = plugin
        self.stop_ev = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_ev.clear()
        self.thread = threading.Thread(target=self._loop, name="nft-scheduler", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_ev.set()

    def _safe(self, name, fn):
        try:
            return fn()
        except Exception:
            log.error("%s:\n%s", name, traceback.format_exc())
            return None

    def _loop(self) -> None:
        self._safe("recover", self.p.orders.recover)
        while not self.stop_ev.wait(TICK):
            if self.p.active:
                self._safe("tick", self.p.orders.tick)
