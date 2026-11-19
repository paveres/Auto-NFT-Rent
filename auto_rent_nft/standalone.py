from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from .app import NftRent
from .bot.access import Access
from .funpay.client import FunPay

log = logging.getLogger("auto_rent_nft.app")


def _merge(defaults: dict, current: dict) -> dict:
    out = dict(defaults)
    for k, v in current.items():
        out[k] = _merge(defaults[k], v) if isinstance(v, dict) and isinstance(defaults.get(k), dict) and k != "texts" else v
    return out


class Settings:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("plugin_settings", {})

    def save(self) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)

    def plugin_settings(self, plugin_id: str, defaults: dict | None = None) -> dict:
        with self.lock:
            merged = _merge(defaults or {}, self.data["plugin_settings"].get(plugin_id, {}))
            self.data["plugin_settings"][plugin_id] = merged
            return merged


class App:
    def __init__(self, env: dict, data_dir: Path):
        self.env = env
        self.data_dir = data_dir
        self.settings = Settings(data_dir / "settings.json")
        proxy = env.get("FUNPAY_PROXY", "").strip()
        if proxy and "://" not in proxy:
            proxy = "http://" + proxy
        self.fp = FunPay(env["FUNPAY_GOLDEN_KEY"].strip(), env.get("FUNPAY_USER_AGENT", "").strip(),
                         {"http": proxy, "https": proxy} if proxy else None)
        self.notifier = None
        self.stopping = threading.Event()
        self.plugin = NftRent(self, data_dir)
        admins = [int(x) for x in env.get("TG_ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()]
        access = Access(data_dir / "admins.json", env.get("TG_PASSWORD", "").strip(), admins)
        self.access = access if env.get("TG_BOT_TOKEN", "").strip() and access.open else None
        keys = {"api_token": env.get("STARSHOP_TOKEN", "").strip(), "api_pin": env.get("STARSHOP_PIN", "").strip(),
                "api_url": env.get("STARSHOP_API", "").strip().rstrip("/")}
        keys = {k: v for k, v in keys.items() if v}
        if keys:
            self.plugin.cfg_set(**keys)

    def notify(self, kind: str, text: str, buttons: list | None = None) -> None:
        if self.notifier:
            self.notifier.notify(kind, text, buttons)

    def stop(self) -> None:
        self.stopping.set()
        self.plugin.stop()
