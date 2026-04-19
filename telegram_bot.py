
import os
import threading
import time
import requests
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USERS = {7173549132, 7050803817}
SELF_URL = os.getenv("SELF_URL", "")

pending_messages = {}
silent_mode = {}

channel_groups = {"vanced": [], "crunchy": []}

# ===== FOOTER SYSTEM =====
footer_enabled = True
footer_title = "Join Backup Channel 👇"
footer_channels = {
    "vanced": [],
    "crunchy": []
}

# ===== WEB =====
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Bot Running"

def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

def ping():
    while True:
        if SELF_URL:
            try:
                requests.get(SELF_URL)
            except:
                pass
        time.sleep(300)

# ===== TEMPLATE =====
def build_template(text, group=None):
    msg = f"👇👇👇\n\n{text}\n\n"

    if footer_enabled and group and footer_channels.get(group):
        msg += f"{footer_title}\n\n"
        for ch in footer_channels[group]:
            msg += f"👉 {ch}\n"

    return msg.strip()

# ===== BUTTONS =====
def preview_buttons(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📺 Footer ON" if footer_enabled else "📺 Footer OFF", callback_data="toggle_footer")],
        [InlineKeyboardButton("✏️ Edit Caption", callback_data="edit_caption")],
        [
            InlineKeyboardButton("🎮 Vanced", callback_data="vanced"),
            InlineKeyboardButton("🍿 Crunchy", callback_data="crunchy"),
        ],
        [InlineKeyboardButton("🚀 Both", callback_data="both")]
    ])

def build_post_buttons(btns):
    if not btns:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(b["name"], url=b["link"])] for b in btns])

# ===== COMMANDS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return
    await update.message.reply_text("Send post content")

# ===== MESSAGE =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    uid = update.effective_user.id
    if uid not in ALLOWED_USERS:
        return

    msg = update.message
    text = msg.text or msg.caption or ""

    # EDIT CAPTION
    if context.user_data.get("edit_caption"):
        pending_messages[uid]["text"] = text
        context.user_data.pop("edit_caption")

        await update.message.reply_text(
            build_template(text, "vanced"),
            reply_markup=preview_buttons(uid)
        )
        return

    # ===== NEW POST =====
    pending_messages[uid] = {
        "text": text,
        "buttons": [],
        "chat_id": msg.chat_id,
        "message_id": msg.message_id,
        "type": "text",
        "file_id": None
    }

    # ✅ FORCE MEDIA DETECTION
    if msg.photo:
        pending_messages[uid]["type"] = "photo"
        pending_messages[uid]["file_id"] = msg.photo[-1].file_id

    elif msg.video:
        pending_messages[uid]["type"] = "video"
        pending_messages[uid]["file_id"] = msg.video.file_id

    elif msg.document:
        pending_messages[uid]["type"] = "document"
        pending_messages[uid]["file_id"] = msg.document.file_id

    await update.message.reply_text(
        build_template(text, "vanced"),
        reply_markup=preview_buttons(uid)
    )

# ===== SEND =====
async def send(context, cid, data, group):
    caption = build_template(data["text"], group)
    buttons = build_post_buttons(data["buttons"])

    # ✅ TRY COPY (BEST METHOD)
    try:
        await context.bot.copy_message(
            chat_id=cid,
            from_chat_id=data["chat_id"],
            message_id=data["message_id"]
        )
        return
    except:
        pass

    # ✅ FALLBACK TO FILE_ID
    try:
        if data["type"] == "photo" and data["file_id"]:
            await context.bot.send_photo(
                chat_id=cid,
                photo=data["file_id"],
                caption=caption,
                reply_markup=buttons
            )

        elif data["type"] == "video" and data["file_id"]:
            await context.bot.send_video(
                chat_id=cid,
                video=data["file_id"],
                caption=caption,
                reply_markup=buttons
            )

        elif data["type"] == "document" and data["file_id"]:
            await context.bot.send_document(
                chat_id=cid,
                document=data["file_id"],
                caption=caption,
                reply_markup=buttons
            )

        else:
            await context.bot.send_message(
                chat_id=cid,
                text=caption,
                reply_markup=buttons
            )

    except Exception as e:
        print("SEND ERROR:", e)
        await context.bot.send_message(chat_id=cid, text=caption)

# ===== CALLBACK =====
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "edit_caption":
        context.user_data["edit_caption"] = True
        await q.message.reply_text("Send new caption")
        return

    if uid not in pending_messages:
        return

    data = pending_messages[uid]

    if q.data == "vanced":
        for cid in channel_groups["vanced"]:
            await send(context, cid, data, "vanced")

    elif q.data == "crunchy":
        for cid in channel_groups["crunchy"]:
            await send(context, cid, data, "crunchy")

    else:
        for cid in channel_groups["vanced"]:
            await send(context, cid, data, "vanced")
        for cid in channel_groups["crunchy"]:
            await send(context, cid, data, "crunchy")

        pending_messages.pop(uid, None)
        await q.message.delete()

# ===== RUN =====
def run():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    app.add_handler(CallbackQueryHandler(callback))

    app.run_polling()

# ===== MAIN =====
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    threading.Thread(target=ping, daemon=True).start()
    run()

