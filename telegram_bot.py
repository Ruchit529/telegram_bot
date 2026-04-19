import os
import time
import threading
import asyncio
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
from deep_translator import GoogleTranslator
from telegram.error import TelegramError

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")

ALLOWED_USERS = {7173549132, 7050803817}
SELF_URL = os.getenv("SELF_URL", "")

translator = GoogleTranslator(source="auto", target="en")

pending_messages = {}
silent_mode = {}

# ===== FOOTER CHANNELS =====
channel_links = [
    "@free_crunchyroll_account_4u",
    "@Crunchyroll_Anime_Chatt"
]

# ===== POSTING GROUPS =====
channel_groups = {
    "vanced": [],
    "crunchy": []
}

MESSAGE_TIMEOUT = 600

# ===== FLASK =====
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Bot Alive", 200

def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

# ===== KEEP ALIVE =====
session = requests.Session()

def ping_self():
    if not SELF_URL:
        return
    while True:
        try:
            session.get(SELF_URL, timeout=10)
        except:
            pass
        time.sleep(300)

# ===== CLEANUP =====
def cleanup_pending():
    now = time.time()
    expired = [
        uid for uid, data in pending_messages.items()
        if now - data["time"] > MESSAGE_TIMEOUT
    ]
    for uid in expired:
        pending_messages.pop(uid, None)

# ===== TEMPLATE =====
def build_template(text):
    result = f"👇👇👇\n\n{text or ''}\n\n"

    if channel_links:
        result += "Join Backup Channel 👇\n\n"
        for ch in channel_links:
            result += f"👉 {ch}\n"

    return result.strip()

# ===== BUTTON MARKUP =====
def post_button(buttons):
    if not buttons:
        return None

    keyboard = []
    for btn in buttons:
        keyboard.append([InlineKeyboardButton(btn["name"], url=btn["link"])])

    return InlineKeyboardMarkup(keyboard)

# ===== PREVIEW BUTTONS =====
def buttons(user_id):
    silent = silent_mode.get(user_id, False)
    notify_text = "🔕 Silent Mode ON" if silent else "🔔 Silent Mode OFF"

    keyboard = [
        [InlineKeyboardButton(notify_text, callback_data="toggle_notify")],
        [InlineKeyboardButton("➕ Add Button", callback_data="add_button")],
        [InlineKeyboardButton("✏ Edit Caption", callback_data="edit")],
        [
            InlineKeyboardButton("🎮 Vanced Games", callback_data="vanced"),
            InlineKeyboardButton("🍿 Crunchyroll Anime", callback_data="crunchy"),
        ],
        [InlineKeyboardButton("🚀 Send to Both", callback_data="both")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ]

    return InlineKeyboardMarkup(keyboard)

# ===== ADMIN PANEL =====
def admin_panel():
    keyboard = [
        [InlineKeyboardButton("📡 Post Channels", callback_data="panel_post")],
        [InlineKeyboardButton("📺 Footer Channels", callback_data="panel_footer")],
        [InlineKeyboardButton("❌ Close", callback_data="panel_close")]
    ]
    return InlineKeyboardMarkup(keyboard)

def post_panel():
    keyboard = [
        [InlineKeyboardButton("➕ Add Vanced", callback_data="add_vanced")],
        [InlineKeyboardButton("➕ Add Crunchy", callback_data="add_crunchy")],
        [InlineKeyboardButton("📋 Show Channels", callback_data="show_post")],
        [InlineKeyboardButton("🔙 Back", callback_data="panel_back")]
    ]
    return InlineKeyboardMarkup(keyboard)

def footer_panel():
    keyboard = [
        [InlineKeyboardButton("➕ Add Footer Channel", callback_data="add_footer")],
        [InlineKeyboardButton("📋 Show Footer Channels", callback_data="show_footer")],
        [InlineKeyboardButton("🔙 Back", callback_data="panel_back")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ===== START =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ALLOWED_USERS:
        return
    await update.message.reply_text("Send text/photo/video to create post.")

# ===== PANEL COMMAND =====
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ALLOWED_USERS:
        return
    await update.message.reply_text("⚙️ Admin Panel", reply_markup=admin_panel())

# ===== HANDLE MESSAGE =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    cleanup_pending()
    user_id = update.message.from_user.id

    if user_id not in ALLOWED_USERS:
        return

    # PANEL INPUT
    if context.user_data.get("add_post"):
        group = context.user_data["add_post"]
        cid = update.message.text

        if cid not in channel_groups[group]:
            channel_groups[group].append(cid)

        await update.message.reply_text(f"✅ Added to {group}")
        context.user_data["add_post"] = None
        return

    if context.user_data.get("add_footer"):
        ch = update.message.text

        if ch not in channel_links:
            channel_links.append(ch)

        await update.message.reply_text("✅ Footer channel added")
        context.user_data["add_footer"] = None
        return

    # BUTTON FLOW
    if user_id in pending_messages:
        data = pending_messages[user_id]

        if data.get("adding_button"):

            if data.get("step") == "name":
                data["temp_name"] = update.message.text
                data["step"] = "link"
                await update.message.reply_text("Now send button link.")
                return

            elif data.get("step") == "link":
                data["buttons"].append({
                    "name": data["temp_name"],
                    "link": update.message.text
                })

                data["adding_button"] = False
                data["step"] = None

                await update.message.reply_text("✅ Button added!", reply_markup=buttons(user_id))
                return

    # EDIT
    if context.user_data.get("editing"):
        pending_messages[user_id]["text"] = update.message.text
        await update.message.reply_text(
            build_template(update.message.text),
            reply_markup=buttons(user_id)
        )
        context.user_data["editing"] = False
        return

    text = update.message.text or update.message.caption or ""
    translated = text

    data = {
        "text": translated,
        "time": time.time(),
        "buttons": [],
        "adding_button": False,
        "step": None,
        "type": "text"
    }

    await update.message.reply_text(
        build_template(translated),
        reply_markup=buttons(user_id)
    )

    pending_messages[user_id] = data

# ===== SEND POST =====
async def send_post(context, cid, data, silent):

    markup = post_button(data.get("buttons"))

    try:
        await context.bot.send_message(
            chat_id=cid,
            text=build_template(data["text"]),
            disable_notification=silent,
            reply_markup=markup
        )
    except TelegramError:
        pass

# ===== BUTTON HANDLER =====
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if user_id not in pending_messages and not query.data.startswith("panel"):
        await query.message.delete()
        return

    data = pending_messages.get(user_id, {})

    # PANEL NAV
    if query.data == "panel_post":
        await query.edit_message_text("📡 Post Channels", reply_markup=post_panel())
        return

    if query.data == "panel_footer":
        await query.edit_message_text("📺 Footer Channels", reply_markup=footer_panel())
        return

    if query.data == "panel_back":
        await query.edit_message_text("⚙️ Admin Panel", reply_markup=admin_panel())
        return

    if query.data == "panel_close":
        await query.message.delete()
        return

    # ADD FROM PANEL
    if query.data == "add_vanced":
        context.user_data["add_post"] = "vanced"
        await query.message.reply_text("Send channel ID for VANCED")
        return

    if query.data == "add_crunchy":
        context.user_data["add_post"] = "crunchy"
        await query.message.reply_text("Send channel ID for CRUNCHY")
        return

    if query.data == "add_footer":
        context.user_data["add_footer"] = True
        await query.message.reply_text("Send @channel")
        return

    if query.data == "show_post":
        text = ""
        for g, ids in channel_groups.items():
            text += f"{g}:\n" + "\n".join(ids) + "\n\n"
        await query.message.reply_text(text)
        return

    if query.data == "show_footer":
        text = "\n".join(channel_links)
        await query.message.reply_text(text)
        return

    # NORMAL FLOW
    if query.data == "toggle_notify":
        silent_mode[user_id] = not silent_mode.get(user_id, False)
        await query.edit_message_reply_markup(reply_markup=buttons(user_id))
        return

    if query.data == "add_button":
        data["adding_button"] = True
        data["step"] = "name"
        await query.message.reply_text("Send button name.")
        return

    if query.data == "edit":
        context.user_data["editing"] = True
        await query.message.reply_text("Send new caption.")
        return

    if query.data == "cancel":
        pending_messages.pop(user_id, None)
        await query.message.delete()
        return

    if query.data == "vanced":
        channels = channel_groups["vanced"]
    elif query.data == "crunchy":
        channels = channel_groups["crunchy"]
    else:
        channels = channel_groups["vanced"] + channel_groups["crunchy"]

    for cid in channels:
        await send_post(context, cid, data, False)

    pending_messages.pop(user_id, None)
    await query.message.delete()

# ===== HELP =====
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
📖 Bot Commands Guide

Groups:
vanced
crunchy

/panel - Open admin panel
"""
    await update.message.reply_text(text)

# ===== RUN =====
def run_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("panel", panel))

    app.add_handler(MessageHandler(filters.ALL, handle_message))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot running...")
    app.run_polling()

# ===== MAIN =====
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    threading.Thread(target=ping_self, daemon=True).start()
    run_bot()
