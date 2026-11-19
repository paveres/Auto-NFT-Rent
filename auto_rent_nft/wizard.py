from __future__ import annotations

import getpass
import re
from pathlib import Path

import requests
from dotenv import dotenv_values

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0.0.0 Safari/537.36")
DEFAULT_API = "https://api.rusksmm.ru/v1"
KEYS = ["FUNPAY_GOLDEN_KEY", "FUNPAY_USER_AGENT", "FUNPAY_PROXY", "STARSHOP_TOKEN", "STARSHOP_PIN", "STARSHOP_API",
        "TG_BOT_TOKEN", "TG_PASSWORD", "TG_ADMIN_IDS"]
TOTAL = 4
LINE = "━" * 44


def read_env(path: Path) -> dict:
    return {k: (v or "") for k, v in dotenv_values(path).items()} if path.exists() else {}


def write_env(path: Path, env: dict) -> None:
    lines = [f"{k}={env.get(k, '')}" for k in KEYS]
    lines += [f"{k}={v}" for k, v in env.items() if k not in KEYS]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def need_setup(env: dict) -> bool:
    return not all(env.get(k) for k in ("FUNPAY_GOLDEN_KEY", "STARSHOP_TOKEN", "STARSHOP_PIN"))


def check_golden(key: str, ua: str, proxy: str) -> str | None:
    from FunPayAPI import Account
    try:
        proxies = {"http": proxy, "https": proxy} if proxy else None
        acc = Account(key, user_agent=ua or DEFAULT_UA, requests_timeout=20, proxy=proxies)
        acc.get()
        return acc.username or None
    except Exception:
        return None


def check_api(url: str, token: str, pin: str) -> float | None:
    from .api import ApiError, StarShopAPI
    try:
        return StarShopAPI(lambda: {"api_url": url, "api_token": token, "api_pin": pin}).balance()
    except (ApiError, KeyError, ValueError):
        return None


def check_bot(token: str) -> str | None:
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15).json()
        return r["result"]["username"] if r.get("ok") else None
    except (requests.RequestException, KeyError, ValueError):
        return None


def head(n: int, title: str) -> None:
    print(f"\n{LINE}\n  Шаг {n} из {TOTAL} · {title}\n{LINE}")


def ask(prompt: str, pattern: str | None = None, error: str = "", optional: bool = False, secret: bool = False) -> str:
    while True:
        try:
            value = (getpass.getpass(prompt) if secret else input(prompt)).strip()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit(1)
        if not value and optional:
            return ""
        if value and (pattern is None or re.fullmatch(pattern, value)):
            return value
        print(f"   ⚠️ {error or 'Неверный формат'}. Попробуйте ещё раз.")


def step_golden(env: dict) -> None:
    head(1, "Вход в FunPay")
    print("1. Откройте funpay.com и войдите в аккаунт продавца")
    print("2. Нажмите F12 → вкладка Application (Приложение) → Cookies → https://funpay.com")
    print("3. Найдите строку golden_key и скопируйте её значение (32 символа)\n")
    while True:
        key = ask("golden_key → ", r"[A-Za-z0-9]{32}", "golden_key состоит из 32 букв и цифр")
        print("   Проверяю…")
        name = check_golden(key, env.get("FUNPAY_USER_AGENT", ""), env.get("FUNPAY_PROXY", ""))
        if name:
            print(f"   ✅ Вошли в FunPay как {name}")
            env["FUNPAY_GOLDEN_KEY"] = key
            return
        print("   ❌ FunPay не принял ключ. Скопируйте golden_key заново")


def step_api(env: dict) -> None:
    head(2, "Ключ API аренды")
    print("1. Откройте в Telegram бота @BlimyStarsBot")
    print("2. Профиль → API → «Выпустить ключ»")
    print("3. Бот покажет токен (12 символов) и PIN (5 цифр). PIN виден один раз\n")
    url = env.get("STARSHOP_API") or DEFAULT_API
    while True:
        token = ask("Токен API → ", r"[A-Za-z0-9]{12}", "токен состоит из 12 букв и цифр")
        pin = ask("PIN → ", r"\d{5}", "PIN состоит из 5 цифр")
        print("   Проверяю…")
        balance = check_api(url, token, pin)
        if balance is not None:
            print(f"   ✅ API подключён, баланс {balance:.2f} ₽")
            env.update(STARSHOP_TOKEN=token, STARSHOP_PIN=pin, STARSHOP_API=url)
            return
        print("   ❌ API не принял токен или PIN. Введите заново")


def step_bot(env: dict) -> None:
    head(3, "Telegram-бот управления (по желанию)")
    print("Через бота приходят заказы, оплаты, ошибки, а в меню можно менять настройки и лоты")
    print("1. Откройте @BotFather → /newbot → придумайте имя")
    print("2. Скопируйте токен вида 123456:ABC…")
    print("Нет бота или не нужен — просто нажмите Enter\n")
    while True:
        token = ask("Токен бота → ", r"\d{5,}:[A-Za-z0-9_-]{30,}", "токен вида 123456:ABC…", optional=True)
        if not token:
            env["TG_BOT_TOKEN"] = env["TG_PASSWORD"] = ""
            print("   Пропускаю: уведомлений и меню не будет")
            return
        username = check_bot(token)
        if username:
            print(f"   ✅ Бот @{username}")
            env["TG_BOT_TOKEN"] = token
            return
        print("   ❌ Telegram не принял токен")


def step_password(env: dict) -> None:
    head(4, "Пароль для бота")
    if not env.get("TG_BOT_TOKEN"):
        print("Бот не задан, шаг пропущен")
        return
    print("Бот личный: при первом /start он попросит пароль. Кто введёт верный пароль, тот получит доступ")
    print("Придумайте пароль от 6 символов (при вводе он не отображается)\n")
    while True:
        first = ask("Пароль → ", r".{6,64}", "нужно от 6 до 64 символов", secret=True)
        if ask("Ещё раз → ", secret=True) == first:
            env["TG_PASSWORD"] = first
            print("   ✅ Пароль сохранён")
            return
        print("   ❌ Пароли не совпали")


def run(path: Path, force: bool = False) -> dict:
    env = read_env(path)
    env["FUNPAY_USER_AGENT"] = env.get("FUNPAY_USER_AGENT") or DEFAULT_UA
    print(f"\n💎 NFT Rent · настройка\nЗаймёт пару минут. Ответы сохраняются в {path.name}")
    if force or not env.get("FUNPAY_GOLDEN_KEY"):
        step_golden(env)
    if force or not (env.get("STARSHOP_TOKEN") and env.get("STARSHOP_PIN")):
        step_api(env)
    if force or "TG_BOT_TOKEN" not in env:
        step_bot(env)
    if env.get("TG_BOT_TOKEN") and (force or not env.get("TG_PASSWORD")):
        step_password(env)
    write_env(path, env)
    print(f"\n{LINE}\n  ✅ Готово. Поменять позже: python main.py setup\n{LINE}\n")
    return env
