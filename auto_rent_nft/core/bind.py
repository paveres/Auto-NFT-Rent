from __future__ import annotations

import html
import json
import re
import urllib.parse

import requests

TC_RE = re.compile(r"tc://\?[A-Za-z0-9_%&=.~+\-]+")
TC_PIECE_RE = re.compile(r"[A-Za-z0-9_%&=.~+\-]{6,}")
CHANNEL_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z][A-Za-z0-9_]{3,31})\b|^@([A-Za-z][A-Za-z0-9_]{3,31})$")
PRIVATE_RE = re.compile(r"t\.me/(?:\+|joinchat/)")


def tc_complete(link: str) -> bool:
    q = urllib.parse.parse_qs(link.split("?", 1)[-1])
    try:
        req = json.loads(q["r"][0])
    except (KeyError, ValueError):
        return False
    return bool(re.fullmatch(r"[0-9a-f]{64}", q.get("id", [""])[0])) and \
        any(i.get("name") == "ton_proof" and i.get("payload") for i in req.get("items", []))


def channel_tc(name: str) -> tuple[str | None, bool]:
    page = requests.get(f"https://t.me/s/{name}", timeout=20, headers={"User-Agent": "Mozilla/5.0"}).text
    posts = [re.sub(r"\s+", "", html.unescape(re.sub(r"<[^>]+>", "", b)))
             for b in re.findall(r'<div class="tgme_widget_message_text[^>]*>([\s\S]*?)</div>', page)]
    seen = False
    for text in reversed(posts + ["".join(posts)]):
        for link in reversed(TC_RE.findall(text)):
            seen = True
            if tc_complete(link):
                return link, True
    return None, seen
