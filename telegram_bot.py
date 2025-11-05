import os
import asyncio
import threading
import time
import requests
from flask import Flask
from telegram import Update, MessageEntity
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from deep_translator import GoogleTranslator
from telegram.error import TelegramError

# === CONFIGURATION ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_IDS = ["-1003052492544", "-1003238213356"]  # ✅ your channels
ALLOWED_USERS = [7173549132]  # ✅ your Telegram user ID
SELF_URL = os.getenv("SELF_URL", "https://telegram_bot_w8pe.onrender.com")
GROUP_LINK = "https://t.me/steam_games_chatt"  # ✅ your group link

translator = GoogleTranslator(source="auto", target="en")
pending_messages = {}
MESSAGE_TIMEOUT = 120  # 2 min cleanup


# === SIMPLE FLASK WEB SERVER ===
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Telegram bot is running on Render!", 200


def run_web():
    port = int(os.getenv("PORT", 10000))
    print(f"🌐 Web server running on port {port}")
    app_web.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# === KEEP ALIVE ===
def ping_self():
    while True:
        try:
            res = requests.get(SELF_URL)
            print(f"🔁 Ping {SELF_URL} | Status: {res.status_code}")
        except Exception as e:
            print(f"⚠️ Ping failed: {e}")
        time.sleep(300)


# === CLEANUP PENDING ===
def cleanup_pending():
    now = time.time()
    expired = [uid for uid, d in pending_messages.items() if now - d["time"] > MESSAGE_TIMEOUT]
    for uid in expired:
        del pending_messages[uid]


# === TEMPLATE BUILDER (Entity-safe) ===
def build_template_with_entities(original_text: str, original_entities=None):
    """
    Builds a Telegram entity-safe message template:
    👇👇👇
    original message
    👉 JOIN GROUP (clickable)
    """
    prefix = "👇👇👇\n\n"
    suffix = "\n\n👉 JOIN GROUP"

    if original_text is None:
        original_text = ""

    full_text = prefix + original_text + suffix
    new_entities = []

    # Preserve user formatting (bold, italic, monospace, etc.)
    if original_entities:
        for ent in original_entities:
            shifted = ent.offset + len(prefix)
            new_entities.append(
                MessageEntity(
                    type=ent.type,
                    offset=shifted,
                    length=ent.length,
                    url=getattr(ent, "url", None),
                    user=getattr(ent, "user", None),
                    language=getattr(ent, "language", None)
                )
            )

    # Add JOIN GROUP clickable link
    join_offset = len(full_text) - len("JOIN GROUP")
    join_entity = MessageEntity(type="text_link", offset=join_offset, length=len("JOIN GROUP"), url=GROUP_LINK)
    new_entities.append(join_entity)

    return full_text, new_entities


# === TELEGRAM BOT LOGIC ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS:
        return await update.message.reply_text("🚫 You are not authorized to use this bot.")
    await update.message.reply_text("👋 Hi! Send text, photo, or video — I'll translate & confirm before posting.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_pending()
    msg = update.message
    user_id = msg.from_user.id

    if user_id not in ALLOWED_USERS:
        return await msg.reply_text("🚫 Unauthorized user.")

    text = msg.caption or msg.text
    entities = msg.caption_entities or msg.entities
    photo = msg.photo
    video = msg.video

    # === CONFIRM HANDLING ===
    if user_id in pending_messages:
        response = (msg.text or "").strip().lower()
        data = pending_messages[user_id]

        # ✅ Confirm
        if response in ["yes", "y", "ok", "send"]:
            formatted_text, ents = build_template_with_entities(data["text"], data.get("entities"))

            for cid in CHANNEL_IDS:
                try:
                    if data["type"] == "text":
                        await context.bot.send_message(chat_id=cid, text=formatted_text, entities=ents)
                    elif data["type"] == "photo":
                        await context.bot.send_photo(chat_id=cid, photo=data["file_id"], caption=formatted_text, caption_entities=ents)
                    elif data["type"] == "video":
                        await context.bot.send_video(chat_id=cid, video=data["file_id"], caption=formatted_text, caption_entities=ents)
                except TelegramError as e:
                    print(f"⚠️ Failed to send to {cid}: {e}")

            await msg.reply_text("✅ Sent to all channels!")
            del pending_messages[user_id]
            return

        # ❌ Cancel
        elif response in ["no", "n", "cancel"]:
            await msg.reply_text("❌ Cancelled.")
            del pending_messages[user_id]
            return

        # ✏️ Edit
        else:
            pending_messages[user_id]["text"] = msg.text
            pending_messages[user_id]["entities"] = msg.entities
            preview, ents = build_template_with_entities(msg.text, msg.entities)
            await msg.reply_text(
                f"✏️ Updated preview:\n\n{preview}\n\nNow reply 'Yes' to send.",
                entities=ents,
                disable_web_page_preview=True
            )
            return

    # === NEW MESSAGE ===
    translated_text = translator.translate(text) if text else ""
    data = {
        "type": "text",
        "text": translated_text,
        "entities": entities,
        "time": time.time(),
    }

    if photo:
        data["type"] = "photo"
        data["file_id"] = photo[-1].file_id
    elif video:
        data["type"] = "video"
        data["file_id"] = video.file_id

    pending_messages[user_id] = data
    preview, ents = build_template_with_entities(translated_text, entities)

    if photo:
        await msg.reply_photo(photo=data["file_id"], caption=f"{preview}\n\nSend to channel? (Yes / No)", caption_entities=ents)
    elif video:
        await msg.reply_video(video=data["file_id"], caption=f"{preview}\n\nSend to channel? (Yes / No)", caption_entities=ents)
    else:
        await msg.reply_text(f"{preview}\n\nSend to channel? (Yes / No)", entities=ents, disable_web_page_preview=True)


# === BOT RUNNER ===
async def run_bot():
    app_tg = ApplicationBuilder().token(BOT_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, handle_message))

    print("🚀 Telegram bot is running...")
    await app_tg.initialize()
    await app_tg.start()
    await app_tg.updater.start_polling()
    await asyncio.Event().wait()


# === MAIN ===
if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    threading.Thread(target=ping_self, daemon=True).start()
    asyncio.run(run_bot())
