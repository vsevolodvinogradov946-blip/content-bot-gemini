import telebot
import os
import requests
from flask import Flask
from threading import Thread

# ─────────────────────────────────────────────────────────────
# КОНФИГУРАЦИЯ (из переменных окружения Render)
# ─────────────────────────────────────────────────────────────
TOKEN      = os.environ.get('TOKEN')       # токен бота от @BotFather
ADMIN_ID   = os.environ.get('ADMIN_ID')    # твой Telegram ID от @userinfobot
CHANNEL_ID = os.environ.get('CHANNEL_ID') # @username_канала
GROQ_KEY   = os.environ.get('GROQ_KEY')   # ключ с console.groq.com

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"

bot = telebot.TeleBot(TOKEN)

# ─────────────────────────────────────────────────────────────
# ХРАНЕНИЕ СЕССИЙ
# ─────────────────────────────────────────────────────────────
sessions      = {}   # uid -> {post_id, text, mode, history}
published_ids = set()

# ─────────────────────────────────────────────────────────────
# КОНТЕНТ-ПЛАН (16 постов, 4 недели)
# ─────────────────────────────────────────────────────────────
CONTENT_PLAN = [
    {"id": 0,  "week": 1, "type": "edu",  "topic": "Чек-лист: 7 признаков того, что бухгалтер вам не подходит"},
    {"id": 1,  "week": 1, "type": "case", "topic": "Кейс: сэкономили 1.2 млн ₽ на налогах для производственной компании"},
    {"id": 2,  "week": 1, "type": "news", "topic": "Изменения в НК 2025: что важно знать директору прямо сейчас"},
    {"id": 3,  "week": 1, "type": "sell", "topic": "Бесплатный аудит вашей бухгалтерии — что мы проверяем за 45 минут"},
    {"id": 4,  "week": 2, "type": "edu",  "topic": "ВЭД и валютный контроль: 5 ошибок, которые видим чаще всего"},
    {"id": 5,  "week": 2, "type": "case", "topic": "Кейс: восстановили учёт после ухода штатного бухгалтера за 3 недели"},
    {"id": 6,  "week": 2, "type": "edu",  "topic": "Дивиденды vs зарплата директора: что выгоднее и как считать"},
    {"id": 7,  "week": 2, "type": "news", "topic": "Требования ФНС растут: как подготовиться к камеральной проверке"},
    {"id": 8,  "week": 3, "type": "edu",  "topic": "Группа компаний: как правильно структурировать и не попасть на дробление"},
    {"id": 9,  "week": 3, "type": "case", "topic": "Кейс: помогли пройти выездную налоговую проверку без штрафов"},
    {"id": 10, "week": 3, "type": "edu",  "topic": "УСН или ОСНО для компании с оборотом от 50 млн — разбираем критерии"},
    {"id": 11, "week": 3, "type": "sell", "topic": "Почему банковская бухгалтерия не подходит для среднего бизнеса"},
    {"id": 12, "week": 4, "type": "edu",  "topic": "Займы между компаниями группы: риски и как их снизить"},
    {"id": 13, "week": 4, "type": "case", "topic": "Кейс: оптимизировали налоговую нагрузку на 18% для торговой компании"},
    {"id": 14, "week": 4, "type": "news", "topic": "Маркировка, ЭДО, новые форматы отчётности — дайджест изменений"},
    {"id": 15, "week": 4, "type": "sell", "topic": "Как мы работаем: 5 шагов от заявки до результата"},
]

TYPE_LABELS = {
    "edu":  "📚 Образовательный",
    "case": "📊 Кейс",
    "news": "📰 Новость + комментарий",
    "sell": "💼 Продающий",
}

SYSTEM_PROMPT = """Ты — контент-менеджер и копирайтер для Telegram-канала аутсорсинговой бухгалтерии.
Аудитория: владельцы и директора компаний 20–100 сотрудников в России.

Правила написания постов:
- Длина: 800–1200 символов
- Тон: экспертный, живой — не официозный и не панибратский
- Структура: Крючок (1–2 строки) → Суть → Практическая ценность → CTA
- Никаких шаблонных фраз: «В современном мире», «Не секрет что», «Актуально как никогда»
- Конкретные цифры, сценарии, примеры из практики
- 2–4 эмодзи — только в начале абзацев, не в каждом слове
- В конце: мягкий призыв — вопрос к аудитории или «напишите в ЛС»
- 2–3 хэштега в самом конце: #налоги #бухгалтерия #бизнес

Форматы по типам:
- edu: чек-лист или разбор ситуации с пошаговой логикой
- case: история без имён — проблема → действия → результат в цифрах
- news: новость 1–2 предложения + комментарий «что это значит для вас»
- sell: польза 70%, продажа 30% — не «купите», а «попробуйте / узнайте»

Отвечай ТОЛЬКО текстом поста, без вступлений типа «Конечно!» или «Вот пост:»."""


# ─────────────────────────────────────────────────────────────
# ГЕНЕРАЦИЯ ЧЕРЕЗ GROQ
# ─────────────────────────────────────────────────────────────
def ai_generate(topic: str, post_type: str, history: list = None) -> str:
    """Отправляет запрос в Groq API (бесплатно, без лимитов)."""

    if history:
        # Режим редактирования — передаём историю диалога
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    else:
        # Первая генерация
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Напиши пост для Telegram-канала.\n"
                f"Тема: {topic}\n"
                f"Тип: {TYPE_LABELS.get(post_type, post_type)}"
            )}
        ]

    headers = {
        "Authorization": f"Bearer {GROQ_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "llama-3.3-70b-versatile",  # лучшая бесплатная модель на Groq
        "messages": messages,
        "max_tokens": 1000,
        "temperature": 0.8,
    }

    response = requests.post(GROQ_URL, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


# ─────────────────────────────────────────────────────────────
# КЛАВИАТУРЫ
# ─────────────────────────────────────────────────────────────
def kb_main():
    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(telebot.types.InlineKeyboardButton("✍️ Сгенерировать пост на сегодня", callback_data="gen_today"))
    kb.add(telebot.types.InlineKeyboardButton("📅 Выбрать пост из плана", callback_data="show_plan"))
    return kb


def kb_plan():
    kb = telebot.types.InlineKeyboardMarkup()
    for p in CONTENT_PLAN:
        done = "✅" if p["id"] in published_ids else "⬜"
        label = f"{done} Нед.{p['week']} | {p['topic'][:40]}…"
        kb.add(telebot.types.InlineKeyboardButton(label, callback_data=f"pick_{p['id']}"))
    kb.add(telebot.types.InlineKeyboardButton("🏠 Назад", callback_data="menu"))
    return kb


def kb_actions():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("✅ Опубликовать", callback_data="publish"),
        telebot.types.InlineKeyboardButton("✏️ Редактировать", callback_data="edit"),
    )
    kb.add(
        telebot.types.InlineKeyboardButton("🔄 Перегенерировать", callback_data="regen"),
        telebot.types.InlineKeyboardButton("🏠 Меню", callback_data="menu"),
    )
    return kb


def kb_after_edit():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("✅ Опубликовать", callback_data="publish"),
        telebot.types.InlineKeyboardButton("✏️ Ещё правки", callback_data="edit"),
    )
    kb.add(
        telebot.types.InlineKeyboardButton("🔄 Перегенерировать", callback_data="regen"),
        telebot.types.InlineKeyboardButton("🏠 Меню", callback_data="menu"),
    )
    return kb


# ─────────────────────────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────────────────────────
def is_admin(message_or_call):
    return str(message_or_call.from_user.id) == str(ADMIN_ID)


def do_generate_and_show(chat_id, message_id, idx: int):
    p = CONTENT_PLAN[idx]
    uid = str(chat_id)

    bot.edit_message_text(
        f"⏳ Генерирую пост...\n\n_{p['topic']}_",
        chat_id, message_id, parse_mode="Markdown",
    )
    try:
        text = ai_generate(p["topic"], p["type"])

        sessions[uid] = {
            "post_id": idx,
            "text": text,
            "mode": None,
            "history": [
                {"role": "user", "content": (
                    f"Напиши пост для Telegram-канала.\n"
                    f"Тема: {p['topic']}\n"
                    f"Тип: {TYPE_LABELS[p['type']]}"
                )},
                {"role": "assistant", "content": text},
            ],
        }

        bot.edit_message_text(
            f"*{TYPE_LABELS[p['type']]}*\n_{p['topic']}_\n\n{text}",
            chat_id, message_id,
            parse_mode="Markdown",
            reply_markup=kb_actions(),
        )
    except Exception as e:
        bot.edit_message_text(
            f"❌ Ошибка: {e}\n\nПроверь GROQ_KEY в переменных Render.",
            chat_id, message_id,
            reply_markup=kb_main(),
        )


# ─────────────────────────────────────────────────────────────
# КОМАНДЫ
# ─────────────────────────────────────────────────────────────
@bot.message_handler(commands=['start'])
def cmd_start(message):
    if not is_admin(message):
        bot.send_message(message.chat.id, "Этот бот только для администратора канала.")
        return
    bot.send_message(
        message.chat.id,
        "👋 *Контент-бот для бухгалтерского канала*\n\nВыбери действие:",
        parse_mode="Markdown",
        reply_markup=kb_main(),
    )


# ─────────────────────────────────────────────────────────────
# КНОПКИ
# ─────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "menu")
def cb_menu(call):
    if not is_admin(call):
        return
    bot.edit_message_text(
        "👋 *Контент-бот для бухгалтерского канала*\n\nВыбери действие:",
        call.message.chat.id, call.message.message_id,
        parse_mode="Markdown",
        reply_markup=kb_main(),
    )


@bot.callback_query_handler(func=lambda c: c.data == "gen_today")
def cb_gen_today(call):
    if not is_admin(call):
        return
    from datetime import date
    idx = (date.today() - date(2025, 1, 1)).days % len(CONTENT_PLAN)
    do_generate_and_show(call.message.chat.id, call.message.message_id, idx)


@bot.callback_query_handler(func=lambda c: c.data == "show_plan")
def cb_show_plan(call):
    if not is_admin(call):
        return
    bot.edit_message_text(
        "📅 *Контент-план — выбери пост:*\n✅ опубликован  ⬜ не опубликован",
        call.message.chat.id, call.message.message_id,
        parse_mode="Markdown",
        reply_markup=kb_plan(),
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("pick_"))
def cb_pick(call):
    if not is_admin(call):
        return
    idx = int(call.data.split("_")[1])
    do_generate_and_show(call.message.chat.id, call.message.message_id, idx)


@bot.callback_query_handler(func=lambda c: c.data == "regen")
def cb_regen(call):
    if not is_admin(call):
        return
    uid = str(call.from_user.id)
    idx = sessions.get(uid, {}).get("post_id", 0)
    do_generate_and_show(call.message.chat.id, call.message.message_id, idx)


@bot.callback_query_handler(func=lambda c: c.data == "edit")
def cb_edit(call):
    if not is_admin(call):
        return
    uid = str(call.from_user.id)
    session = sessions.get(uid)
    if not session:
        bot.answer_callback_query(call.id, "Сначала сгенерируй пост")
        return
    session["mode"] = "editing"
    bot.edit_message_text(
        f"✏️ *Режим редактирования*\n\nТекущая версия:\n\n{session['text']}\n\n"
        "💬 *Напиши, что изменить:*\n"
        "_Примеры: «сделай короче», «добавь цифры», «измени концовку»_",
        call.message.chat.id, call.message.message_id,
        parse_mode="Markdown",
    )


@bot.callback_query_handler(func=lambda c: c.data == "publish")
def cb_publish(call):
    if not is_admin(call):
        return
    uid = str(call.from_user.id)
    session = sessions.get(uid)
    if not session:
        bot.answer_callback_query(call.id, "Пост не найден")
        return
    try:
        bot.send_message(CHANNEL_ID, session["text"])
        published_ids.add(session["post_id"])
        p = CONTENT_PLAN[session["post_id"]]
        bot.edit_message_text(
            f"🎉 *Пост опубликован!*\n\nТема: _{p['topic']}_\nКанал: {CHANNEL_ID}\n\nЧто дальше?",
            call.message.chat.id, call.message.message_id,
            parse_mode="Markdown",
            reply_markup=kb_main(),
        )
    except Exception as e:
        bot.edit_message_text(
            f"❌ Ошибка публикации: {e}\n\n"
            "Проверь:\n— Бот добавлен в канал как администратор?\n— Правильный CHANNEL_ID?",
            call.message.chat.id, call.message.message_id,
            reply_markup=kb_main(),
        )


# ─────────────────────────────────────────────────────────────
# ТЕКСТ В РЕЖИМЕ РЕДАКТИРОВАНИЯ
# ─────────────────────────────────────────────────────────────
@bot.message_handler(func=lambda m:
    str(m.from_user.id) == str(ADMIN_ID) and
    sessions.get(str(m.from_user.id), {}).get("mode") == "editing")
def handle_edit(message):
    uid = str(message.from_user.id)
    session = sessions[uid]

    session["history"].append({"role": "user", "content": message.text})
    wait_msg = bot.send_message(message.chat.id, "⏳ Редактирую...")

    try:
        new_text = ai_generate("", "", history=session["history"])
        session["history"].append({"role": "assistant", "content": new_text})
        session["text"] = new_text
        session["mode"] = None

        bot.delete_message(message.chat.id, wait_msg.message_id)
        bot.send_message(
            message.chat.id,
            f"✏️ *Обновлённая версия:*\n\n{new_text}",
            parse_mode="Markdown",
            reply_markup=kb_after_edit(),
        )
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", message.chat.id, wait_msg.message_id)


# ─────────────────────────────────────────────────────────────
# ВЕБ-СЕРВЕР (чтобы Render не засыпал)
# ─────────────────────────────────────────────────────────────
app = Flask(__name__)

@app.route('/')
def home():
    return 'Контент-бот работает! ✅'


def run_web():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)


# ─────────────────────────────────────────────────────────────
# ЗАПУСК
# ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    t = Thread(target=run_web)
    t.daemon = True
    t.start()
    print('✅ Контент-бот с Groq запущен...')
    bot.infinity_polling()
