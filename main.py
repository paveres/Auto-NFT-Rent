from __future__ import annotations

import asyncio
import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
ENV = ROOT / ".env"
sys.path.insert(0, str(ROOT))

HELP = """python main.py          запустить
python main.py setup    заново пройти настройку
python main.py check    проверить FunPay и API
"""


def setup_logging() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    DATA.mkdir(exist_ok=True)
    fmt = logging.Formatter("[%(asctime)s] %(levelname)-7s %(name)s: %(message)s", "%d.%m %H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    file = RotatingFileHandler(DATA / "log.txt", maxBytes=3_000_000, backupCount=3, encoding="utf-8")
    file.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[console, file])
    for noisy in ("aiogram.event", "aiogram.dispatcher", "urllib3", "FunPayAPI"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> int:
    from auto_rent_nft import wizard
    args = sys.argv[1:]
    cmd = args[0] if args else "run"
    if cmd in ("-h", "--help", "help"):
        print(HELP)
        return 0
    env = wizard.read_env(ENV)
    if cmd == "setup" or wizard.need_setup(env):
        env = wizard.run(ENV, force=cmd == "setup")
        if cmd == "setup":
            return 0
    setup_logging()
    log = logging.getLogger("main")
    from auto_rent_nft.standalone import App
    app = App(env, DATA)
    p = app.plugin
    try:
        app.fp.connect()
    except Exception as e:
        log.error("FunPay: %s\nПроверьте golden_key: python main.py setup", e)
        return 1
    try:
        me = p.api.me()
        log.info("API: баланс %s ₽, лимит %s/мин", me["client"]["balance_rub"], me["limits"]["per_minute"])
    except Exception as e:
        log.error("API: %s\nПроверьте токен и PIN: python main.py setup", e)
        return 1
    if cmd == "check":
        print("✅ FunPay и API работают")
        return 0
    p.start()
    from auto_rent_nft.funpay.client import Events
    Events(app.fp, p, app.stopping).start()
    log.info("Лот: в описании напишите !rent, в названии подарок и срок")
    log.info("💎 NFT Rent работает. Остановить — Ctrl+C")
    try:
        if app.access is not None:
            from auto_rent_nft.bot.telegram import TelegramPanel
            panel = TelegramPanel(env["TG_BOT_TOKEN"].strip(), app.access, p)
            app.notifier = panel
            asyncio.run(panel.run())
        else:
            log.info("Бот Telegram не задан: уведомлений и меню не будет (python main.py setup)")
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
