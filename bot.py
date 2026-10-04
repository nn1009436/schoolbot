# language: Python, file: bot.py
# Бот школьного паблика БЕЗ внешних библиотек.
# Работает на голом Python. Ничего ставить не надо.

import os
import json
import time
import threading
import urllib.request
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- Фейковый веб-сервер для Render: открывает порт, чтобы Render не валил бота ---
class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *a):
        pass

def run_fake_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), Health).serve_forever()

threading.Thread(target=run_fake_server, daemon=True).start()
# --- конец хака ---

# ================= НАСТРОЙКА =================
# Токен и ID читаются из Environment Variables на Render.
# Если запускаешь локально и переменных нет — впиши сюда строкой.
BOT_TOKEN  = os.environ.get("BOT_TOKEN", "8932271269:AAFkAOE3nBBg07ajmFUkFBuSUxj1XtBHYMo")
ADMIN_ID   = int(os.environ.get("8509351627", "0"))
CHANNEL_ID = -1003921655568
# ============================================

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

pending = {}
last_update_id = 0


def api_call(method, params=None):
    url = f"{API}/{method}"
    if params:
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(url, data=data)
    else:
        req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"[!] API error {method}: {e}")
        return None


def send_message(chat_id, text, reply_markup=None):
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = json.dumps(reply_markup)
    return api_call("sendMessage", params)


def send_photo(chat_id, photo, caption="", reply_markup=None):
    params = {"chat_id": chat_id, "photo": photo, "caption": caption,
              "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = json.dumps(reply_markup)
    return api_call("sendPhoto", params)


def answer_callback(callback_id, text=""):
    return api_call("answerCallbackQuery",
                    {"callback_query_id": callback_id, "text": text})


def edit_reply_markup(chat_id, message_id):
    return api_call("editMessageReplyMarkup",
                    {"chat_id": chat_id, "message_id": message_id,
                     "reply_markup": json.dumps({"inline_keyboard": []})})


def get_updates(offset=0):
    result = api_call("getUpdates", {"offset": offset, "timeout": 25})
    if result and result.get("ok"):
        return result["result"]
    return []


INSTRUCTION = (
    "👋 <b>Привет!</b>\n\n"
    "Это бот школьного паблика. Здесь ты можешь <b>анонимно предложить пост</b>.\n\n"
    "📝 <b>Как подать пост:</b>\n"
    "1. Напиши текст поста (можно с фото).\n"
    "2. Отправь его сюда боту.\n"
    "3. Модератор рассмотрит — и если одобрит, пост выйдет в канале.\n"
    "4. Если отклонит — тебе придёт уведомление.\n\n"
    "⚠️ Не спамь, не пиши мат и личные данные. Такое отклоняется.\n\n"
    "Пиши свой пост — жду!"
)


def handle_message(msg):
    chat = msg.get("chat", {})
    from_user = msg.get("from", {})
    chat_id = chat.get("id")
    user_id = from_user.get("id")
    text = msg.get("text") or msg.get("caption") or ""

    if text == "/start":
        send_message(chat_id, INSTRUCTION)
        return

    if user_id == ADMIN_ID:
        return

    photo_id = None
    if "photo" in msg and msg["photo"]:
        photo_id = msg["photo"][-1]["file_id"]

    if not text and not photo_id:
        send_message(chat_id, "Отправь текст или фото поста.")
        return

    author_name = from_user.get("first_name", "Аноним")
    if from_user.get("last_name"):
        author_name += " " + from_user["last_name"]
    author_user = "@" + from_user["username"] if from_user.get("username") else "—"

    preview  = "📩 <b>Новый пост на модерации</b>\n\n"
    preview += f"👤 <b>Автор:</b> {author_name}\n"
    preview += f"🔗 <b>Юзернейм:</b> {author_user}\n"
    preview += f"🆔 <b>ID:</b> <code>{user_id}</code>\n\n"
    if text:
        preview += f"📝 <b>Текст:</b>\n{text}\n"
    else:
        preview += "📷 Пост без текста (только фото)\n"

    keyboard = {"inline_keyboard": [[
        {"text": "✅ Принять", "callback_data": "approve"},
        {"text": "❌ Отклонить", "callback_data": "reject"},
    ]]}

    if photo_id:
        sent = send_photo(ADMIN_ID, photo_id, preview, keyboard)
    else:
        sent = send_message(ADMIN_ID, preview, keyboard)

    if sent and sent.get("ok"):
        msg_id = sent["result"]["message_id"]
        pending[msg_id] = {
            "author_id": user_id,
            "text": text,
            "photo_id": photo_id,
        }
        send_message(chat_id, "✅ Твой пост отправлен на модерацию. Жди решения!")
    else:
        send_message(chat_id, "⚠️ Ошибка, попробуй позже.")


def handle_callback(cb):
    user_id = cb["from"]["id"]
    cb_id = cb["id"]
    data = cb.get("data")

    if user_id != ADMIN_ID:
        answer_callback(cb_id, "Ты не модератор.")
        return

    msg_id = cb["message"]["message_id"]
    post = pending.get(msg_id)

    if not post:
        answer_callback(cb_id, "Пост уже обработан.")
        return

    edit_reply_markup(ADMIN_ID, msg_id)

    if data == "approve":
        if post["photo_id"]:
            send_photo(CHANNEL_ID, post["photo_id"], post["text"] or "")
        else:
            send_message(CHANNEL_ID, post["text"])
        answer_callback(cb_id, "Опубликовано!")
        send_message(post["author_id"],
                     "🎉 Твой пост одобрен и опубликован!")
    else:
        send_message(post["author_id"],
                     "😔 Ваш пост отклонён модератором.")
        answer_callback(cb_id, "Отклонено.")

    pending.pop(msg_id, None)


def main():
    global last_update_id
    print("[*] Бот запущен. Ctrl+C чтобы остановить.")
    while True:
        try:
            updates = get_updates(last_update_id + 1)
            for upd in updates:
                last_update_id = upd["update_id"]
                if "message" in upd:
                    handle_message(upd["message"])
                elif "callback_query" in upd:
                    handle_callback(upd["callback_query"])
        except KeyboardInterrupt:
            print("\n[*] Остановлен.")
            break
        except Exception as e:
            print(f"[!] Loop error: {e}")
            time.sleep(3)


if __name__ == "__main__":
    main()
