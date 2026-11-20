from __future__ import annotations

DEFAULT_TEXTS: dict[str, str] = {
    "paid": ("✅ Оплачено: {gift} · {days}\n"
             "⚠️ БОТ ВИДИТ ВСЁ, ЧТО ВЫ ПИШЕТЕ! НАПИШИТЕ ОДИН РАЗ И ЖДИТЕ СООБЩЕНИЕ ОТ БОТА. СПАМ МЕШАЕТ РАБОТЕ БОТА!\n"
             "👇 Пришлите номер NFT с картинки"),
    "pick_hint": "👇 Пришлите номер (1–{n})",
    "pick_taken": "😔 Этот NFT уже забрали. Выберите другой 👇",
    "pick_retry": "⚠️ Сбой. Выберите NFT ещё раз 👇",
    "bad_number": "Нет такого номера. Пришлите 1–{n}",
    "chosen": "✅ №{n} · {name}\n⏳ Оформляю, до минуты…",
    "remind": "⏰ Ждём номер NFT с картинки",
    "paused": "⏸ Пауза. Напишите !модель — пришлю картинку",
    "no_stock": "😔 Все {gift} заняты. Продавец скоро ответит",
    "min_days": "📅 {gift} — минимум {min} сут., в заказе {days}. Продавец скоро ответит",
    "seller": "🙏 Продавец скоро ответит",
    "delay": "⏳ Оформление задерживается, продавец в курсе",
    "rented": ("✅ {name} ваш до {until}\n\nКак поставить в профиль?\n"
               "1 — быстро (вход через Telegram)\n2 — вручную (fragment.com)"),
    "bind_choice": "Как поставить в профиль?\n1 — быстро (вход через Telegram)\n2 — вручную (fragment.com)",
    "fast_link": "🔐 Подтвердите вход в Telegram (5 мин):\n📱 {link}\n💻 {pc}\nДальше всё сделаю сам",
    "fast_code": "🔢 Выберите в Telegram число {code}",
    "fast_targets": ("✅ Вход выполнен!\n\n📍 Куда поставить подарок? Пришлите ОДИН номер из списка:\n\n{lines}\n\n"
                     "⏳ На выбор 3 минуты, иначе поставлю в личный аккаунт.\nПосле номера ждите сообщение бота, повторно не пишите"),
    "fast_auto": "⌛ Время на выбор вышло, ставлю в личный аккаунт",
    "fast_limit": "⚠️ Быстрая привязка уже запускалась несколько раз. Поставим вручную, инструкция выше",
    "fast_expired": "⌛ Ссылка устарела. Напишите !привязка",
    "fast_to_manual": "⚠️ Быстро не вышло, давайте вручную:\n\n{manual}",
    "bind_manual": ("🔗 Ручная привязка. Делайте по шагам:\n\n"
                    "1. Создайте в Telegram новый канал и сделайте его публичным (адрес вида t.me/mychannel)\n"
                    "2. Откройте fragment.com и войдите через Telegram\n"
                    "3. Нажмите Connect TON, затем «Copy link» (QR слева вверху)\n"
                    "4. Сразу опубликуйте скопированную ссылку tc:// постом в вашем канале\n"
                    "5. Пришлите сюда ссылку на канал, например t.me/mychannel. Ссылку из поста я найду сам\n\n"
                    "⚠️ После «Copy link» не нажимайте «Назад» и не закрывайте окно Connect TON на Fragment: "
                    "ссылка сбросится и её придётся копировать заново\n\n"
                    "Передумали — пришлите 1"),
    "not_tc": "Нужна ссылка tc:// с fragment.com",
    "tc_cut": "✂️ Ссылка обрезана. Опубликуйте её в открытом канале и пришлите ссылку на канал",
    "channel_looking": "🔎 Смотрю канал…",
    "channel_empty": "В канале нет ссылки tc://. Канал открытый? Пришлите ещё раз",
    "channel_cut": "Ссылка в канале обрезана. Скопируйте заново и опубликуйте новым постом",
    "channel_private": "🔒 Канал закрытый. Нужна ссылка вида t.me/mychannel",
    "bind_working": "⏳ Привязываю…",
    "bind_failed": ("⌛ Ссылка устарела. Скопируйте новую на fragment.com и пришлите канал ещё раз\n\n"
                    "Не нажимайте «Назад» после «Copy link»: так ссылка сбрасывается"),
    "done_fast": "🎉 Готово! {name} {target} до {until}\n🔒 Я вышел из вашего аккаунта",
    "done_auto": "✅ Вход выполнен!\n🎉 Готово! {name} {target} до {until}\n🔒 Я вышел из вашего аккаунта",
    "done_manual": "✅ Привязано до {until}\nНа fragment.com: My Assets → ⋯ → Display on Telegram",
    "ask_review": "🙏 Подтвердите заказ и оставьте отзыв: {order_url}",
    "end_soon": "⏰ {name} у вас до {until}. Продлить — !продлить",
    "ended": "⌛ Аренда {name} закончилась. Взять снова: {link}",
    "help": ("⌨️ Команды\n!подарки — выбрать подарок и посмотреть модели\n!модель — картинка по заказу\n"
             "!привязка — поставить заново\n!срок — сколько осталось\n!продлить — продлить"),
    "nft_list": "🎁 Можно арендовать:\n{lines}\n\nСвободные NFT: !модели <подарок>",
    "nft_empty": "😔 Сейчас всё разобрали",
    "gifts_hint": "👇 Пришлите номер подарка (1–{n}), покажу свободные модели\n{more}",
    "models_caption": ("🖼 Свободные {gift}\n\n⚡ Модели быстро разбирают: любую могут забрать в любую секунду, имейте это в виду\n\n"
                       "🛒 Арендовать: {link}"),
    "unknown_gift": "Нет такого подарка. Список — !нфт",
    "term": "⏱ {name} — до {until} ({left})",
    "term_none": "Активных аренд нет. Что есть — !нфт",
    "extend": "➕ Продлить {name}: оплатите этот же лот ещё раз — {link}",
    "extending": "⏳ Продлеваю {name} на {days}…",
    "extended": "✅ Продлено: {name} ещё на {days}, теперь до {until}",
    "extend_na": "🙏 Продление этого подарка сейчас недоступно. Продавец скоро ответит",
}

TITLES: dict[str, str] = {
    "paid": "После оплаты (картинка)", "pick_hint": "Подсказка: пришлите номер", "pick_taken": "NFT забрали",
    "pick_retry": "Сбой — выбрать заново", "bad_number": "Неверный номер", "chosen": "Номер принят",
    "remind": "Напоминание о выборе", "paused": "Выбор на паузе", "no_stock": "Нет свободных NFT",
    "min_days": "Мало суток в заказе", "seller": "Продавец ответит", "delay": "Задержка оформления",
    "rented": "NFT арендован (1 или 2)", "bind_choice": "Выбор привязки", "fast_link": "Ссылка входа",
    "fast_code": "Число в Telegram", "fast_targets": "Куда поставить", "fast_auto": "Время на выбор вышло", "fast_expired": "Ссылка устарела",
    "fast_to_manual": "Быстро не вышло", "bind_manual": "Инструкция вручную", "not_tc": "Не та ссылка",
    "tc_cut": "Ссылка обрезана", "channel_looking": "Смотрю канал", "channel_empty": "В канале нет ссылки",
    "channel_cut": "В канале ссылка обрезана", "channel_private": "Закрытый канал", "bind_working": "Привязываю",
    "bind_failed": "Привязка не вышла", "done_fast": "Готово (быстро)", "done_auto": "Готово (без выбора места)", "done_manual": "Готово (вручную)",
    "ask_review": "Просьба об отзыве", "end_soon": "Скоро конец аренды", "ended": "Аренда закончилась",
    "help": "!помощь", "nft_list": "!нфт", "nft_empty": "!нфт — пусто", "models_caption": "!модели",
    "unknown_gift": "Подарок не найден", "term": "!срок", "term_none": "!срок — аренд нет", "extend": "!продлить",
}

VARIABLES = "{gift} {days} {n} {name} {model} {backdrop} {until} {link} {pc} {code} {lines} {target} {order_url} {min} {left}"


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


class Texts:
    def __init__(self, cfg):
        self.cfg = cfg

    def raw(self, key: str) -> str:
        return (self.cfg().get("texts") or {}).get(key) or DEFAULT_TEXTS.get(key, key)

    def __call__(self, key: str, **values) -> str:
        if key == "fast_to_manual":
            values.setdefault("manual", self("bind_manual"))
        try:
            return self.raw(key).format_map(_Safe(values)).strip()
        except (ValueError, IndexError):
            return self.raw(key)
