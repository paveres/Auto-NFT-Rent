from __future__ import annotations

NODE = 3064
MARKER = "!rent"

DEFAULTS = {
    "enabled": True,
    "api_url": "https://api.rusksmm.ru/v1",
    "api_token": "",
    "api_pin": "",
    "profit_guard": 0.85,
    "auto_raise": True,
    "pick_limit": 27,
    "remind_after": 600,
    "pause_after": 1800,
    "end_remind": 7200,
    "notify_delivered": True,
    "notify_errors": True,
    "texts": {},
}

STATE_RU = {
    "choosing": "выбирает NFT", "renting": "оформляется", "bind_choice": "выбирает привязку",
    "bind_manual": "привязка вручную", "bind_fast": "быстрая привязка", "bind_target": "выбирает, куда поставить",
    "done": "выдан", "failed": "нужна помощь", "refunded": "возврат", "paused": "на паузе", "extending": "продлевается",
}
ACTIVE = ("choosing", "renting", "bind_choice", "bind_manual", "bind_fast", "bind_target", "paused", "failed", "extending")
BIND = ("bind_choice", "bind_manual", "bind_fast", "bind_target")
