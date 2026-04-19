
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
    silent = silent_mode.get(user_id, False)

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔕 Silent ON" if silent else "🔔 Silent OFF", callback_data="toggle")],
        [InlineKeyboardButton("📺 Footer ON" if footer_enabled else "📺 Footer OFF", callback_data="toggle_footer")],
        [InlineKeyboardButton("➕ Add Button", callback_data="add_btn")],
        [InlineKeyboardButton("✏️ Edit Caption", callback_data="edit_caption")],
        [
            InlineKeyboardButton("🎮 Vanced Games", callback_data="vanced"),
            InlineKeyboardButton("🍿 Crunchyroll Anime", callback_data="crunchy"),
        ],
        [InlineKeyboardButton("🚀 Send to Both", callback_data="both")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])

def build_post_buttons(btns):
    if not btns:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(b["name"], url=b["link"])] for b in btns])

# ===== PANEL =====
def panel_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Post Channels", callback_data="p_post")],
        [InlineKeyboardButton("📺 Footer Settings", callback_data="p_footer")],
        [InlineKeyboardButton("❌ Close", callback_data="p_close")]
    ])

def panel_post():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Vanced", callback_data="add_v")],
        [InlineKeyboardButton("➕ Add Crunchy", callback_data="add_c")],
        [
            InlineKeyboardButton("➖ Remove Vanced", callback_data="remove_v"),
            InlineKeyboardButton("➖ Remove Crunchy", callback_data="remove_c"),
        ],
        [InlineKeyboardButton("📋 Show Channels", callback_data="show_p")],
        [InlineKeyboardButton("🔙 Back", callback_data="p_back")]
    ])

def panel_footer():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏ Set Title", callback_data="set_footer_title")],
        [
            InlineKeyboardButton("➕ Add Vanced", callback_data="add_footer_v"),
            InlineKeyboardButton("➕ Add Crunchy", callback_data="add_footer_c"),
        ],
        [
            InlineKeyboardButton("➖ Remove Vanced", callback_data="remove_footer_v"),
            InlineKeyboardButton("➖ Remove Crunchy", callback_data="remove_footer_c"),
        ],
        [InlineKeyboardButton("📋 Show Footer", callback_data="show_footer")],
        [InlineKeyboardButton("🔙 Back", callback_data="p_back")]
    ])

# ===== COMMANDS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return
    await update.message.reply_text("Send post content")

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚙️ Admin Panel", reply_markup=panel_menu())

# ===== MESSAGE =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    global footer_title

    uid = update.effective_user.id
    if uid not in ALLOWED_USERS:
        return

    text = update.message.text or update.message.caption or ""

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
        "chat_id": update.message.chat_id,
        "message_id": update.message.message_id
    }

    await update.message.reply_text(
        build_template(text, "vanced"),
        reply_markup=preview_buttons(uid)
    )

# ===== SEND =====
async def send(context, cid, data, group):
    caption = build_template(data["text"], group)
    buttons = build_post_buttons(data["buttons"])

    try:
        await context.bot.copy_message(
            chat_id=cid,
            from_chat_id=data["chat_id"],
            message_id=data["message_id"],
            caption=caption,
            reply_markup=buttons
        )
    except:
        await context.bot.send_message(
            chat_id=cid,
            text=caption,
            reply_markup=buttons
        )

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
        return

# ===== RUN =====
def run():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", panel))

    app.add_handler(MessageHandler(filters.ALL, handle_message))
    app.add_handler(CallbackQueryHandler(callback))

    app.run_polling()

# ===== MAIN =====
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    threading.Thread(target=ping, daemon=True).start()
    run()

