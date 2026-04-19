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
channel_groups = {"vanced": [], "crunchy": []}

footer_enabled = True
footer_title = "Join Backup Channel 👇"
footer_channels = []

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
def build_template(text):
    msg = f"👇👇👇\n\n{text}\n\n"

    if footer_enabled and footer_channels:
        msg += f"{footer_title}\n\n"
        for ch in footer_channels:
            msg += f"👉 {ch}\n"

    return msg.strip()

# ===== BUTTONS =====
def preview_buttons(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏ Edit Caption", callback_data="edit_caption")],
        [InlineKeyboardButton("📺 Footer ON" if footer_enabled else "📺 Footer OFF", callback_data="toggle_footer")],
        [
            InlineKeyboardButton("🎮 Vanced", callback_data="vanced"),
            InlineKeyboardButton("🍿 Crunchy", callback_data="crunchy"),
        ],
        [InlineKeyboardButton("🚀 Send to Both", callback_data="both")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])

# ===== COMMAND =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return
    await update.message.reply_text("Send or forward post")

# ===== MESSAGE HANDLER =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    uid = update.effective_user.id
    if uid not in ALLOWED_USERS:
        return

    msg = update.message
    text = msg.text or msg.caption or ""

    # ===== EDIT CAPTION =====
    if context.user_data.get("edit_caption"):
        if uid in pending_messages:
            pending_messages[uid]["text"] = text
            data = pending_messages[uid]

            if data["media"] == "photo":
                await msg.reply_photo(
                    photo=data["file_id"],
                    caption=build_template(text),
                    reply_markup=preview_buttons(uid),
                    parse_mode=None
                )

            elif data["media"] == "video":
                await msg.reply_video(
                    video=data["file_id"],
                    caption=build_template(text),
                    reply_markup=preview_buttons(uid),
                    parse_mode=None
                )

            else:
                await msg.reply_text(
                    build_template(text),
                    reply_markup=preview_buttons(uid),
                    parse_mode=None
                )
        else:
            await msg.reply_text("❌ No post to edit")

        context.user_data.pop("edit_caption")
        return

    # ===== NEW POST =====
    media = None
    file_id = None

    if msg.photo:
        media = "photo"
        file_id = msg.photo[-1].file_id

    elif msg.video:
        media = "video"
        file_id = msg.video.file_id

    pending_messages[uid] = {
        "text": text,
        "media": media,
        "file_id": file_id
    }

    # ===== PREVIEW =====
    if media == "photo":
        await msg.reply_photo(
            photo=file_id,
            caption=build_template(text),
            reply_markup=preview_buttons(uid),
            parse_mode=None
        )

    elif media == "video":
        await msg.reply_video(
            video=file_id,
            caption=build_template(text),
            reply_markup=preview_buttons(uid),
            parse_mode=None
        )

    else:
        await msg.reply_text(
            build_template(text),
            reply_markup=preview_buttons(uid),
            parse_mode=None
        )

# ===== SEND FUNCTION =====
async def send(context, cid, data):

    if data["media"] == "photo":
        await context.bot.send_photo(
            chat_id=cid,
            photo=data["file_id"],
            caption=build_template(data["text"]),
            parse_mode=None
        )

    elif data["media"] == "video":
        await context.bot.send_video(
            chat_id=cid,
            video=data["file_id"],
            caption=build_template(data["text"]),
            parse_mode=None
        )

    else:
        await context.bot.send_message(
            chat_id=cid,
            text=build_template(data["text"]),
            parse_mode=None
        )

# ===== CALLBACK =====
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    global footer_enabled

    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "edit_caption":
        context.user_data["edit_caption"] = True
        await q.message.reply_text("✏ Send new caption")
        return

    if q.data == "toggle_footer":
        footer_enabled = not footer_enabled
        await q.edit_message_reply_markup(reply_markup=preview_buttons(uid))
        return

    if uid not in pending_messages:
        return

    data = pending_messages[uid]

    if q.data == "cancel":
        pending_messages.pop(uid, None)
        await q.message.delete()
        return

    if q.data == "vanced":
        targets = channel_groups["vanced"]
    elif q.data == "crunchy":
        targets = channel_groups["crunchy"]
    else:
        targets = channel_groups["vanced"] + channel_groups["crunchy"]

    for cid in targets:
        await send(context, cid, data)

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