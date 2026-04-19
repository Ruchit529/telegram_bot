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
from telegram.error import TelegramError

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USERS = {7173549132, 7050803817}
SELF_URL = os.getenv("SELF_URL", "")

pending_messages = {}
silent_mode = {}

# ===== DATA =====
channel_links = [
    "@free_crunchyroll_account_4u",
    "@Crunchyroll_Anime_Chatt"
]

channel_groups = {
    "vanced": [],
    "crunchy": []
}

# ===== FLASK =====
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Bot Alive", 200

def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

# ===== KEEP ALIVE =====
def ping_self():
    while True:
        if SELF_URL:
            try:
                requests.get(SELF_URL)
            except:
                pass
        time.sleep(300)

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
    notify_text = "🔕 Silent ON" if silent else "🔔 Silent OFF"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(notify_text, callback_data="toggle_notify")],
        [InlineKeyboardButton("➕ Add Button", callback_data="add_button")],
        [InlineKeyboardButton("✏ Edit Caption", callback_data="edit")],
        [
            InlineKeyboardButton("🎮 Vanced Games", callback_data="vanced"),
            InlineKeyboardButton("🍿 Crunchyroll Anime", callback_data="crunchy"),
        ],
        [InlineKeyboardButton("🚀 Send to Both", callback_data="both")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])

# ===== ADMIN PANEL =====
def admin_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Post Channels", callback_data="panel_post")],
        [InlineKeyboardButton("📺 Footer Channels", callback_data="panel_footer")],
        [InlineKeyboardButton("❌ Close", callback_data="panel_close")]
    ])

def post_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Vanced", callback_data="add_vanced")],
        [InlineKeyboardButton("➕ Add Crunchy", callback_data="add_crunchy")],
        [InlineKeyboardButton("📋 Show Channels", callback_data="show_post")],
        [InlineKeyboardButton("🔙 Back", callback_data="panel_back")]
    ])

def footer_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Footer", callback_data="add_footer")],
        [InlineKeyboardButton("📋 Show Footer", callback_data="show_footer")],
        [InlineKeyboardButton("🔙 Back", callback_data="panel_back")]
    ])

# ===== START =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ALLOWED_USERS:
        return
    await update.message.reply_text("Send message to create post.")

# ===== PANEL =====
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚙️ Admin Panel", reply_markup=admin_panel())

# ===== HANDLE MESSAGE =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.message.from_user.id
    if user_id not in ALLOWED_USERS:
        return

    # ADD POST CHANNEL
    if context.user_data.get("add_post"):
        cid = update.message.text.strip()
        group = context.user_data["add_post"]

        if not cid.startswith("-100"):
            await update.message.reply_text("❌ Invalid ID")
            return

        channel_groups[group].append(cid)
        await update.message.reply_text(f"✅ Added to {group}")

        context.user_data["add_post"] = None
        return

    # ADD FOOTER
    if context.user_data.get("add_footer"):
        ch = update.message.text.strip()

        if not ch.startswith("@"):
            await update.message.reply_text("❌ Must be @channel")
            return

        channel_links.append(ch)
        await update.message.reply_text("✅ Footer added")

        context.user_data["add_footer"] = None
        return

    # BUTTON FLOW
    if user_id in pending_messages:
        data = pending_messages[user_id]

        if data.get("adding_button"):
            if data["step"] == "name":
                data["temp"] = update.message.text
                data["step"] = "link"
                await update.message.reply_text("Send link")
                return
            else:
                data["buttons"].append({"name": data["temp"], "link": update.message.text})
                data["adding_button"] = False
                await update.message.reply_text("✅ Button added", reply_markup=buttons(user_id))
                return

    text = update.message.text
    data = {"text": text, "buttons": [], "adding_button": False, "step": "name"}

    await update.message.reply_text(build_template(text), reply_markup=buttons(user_id))
    pending_messages[user_id] = data

# ===== SEND =====
async def send_post(context, cid, data):
    await context.bot.send_message(
        chat_id=cid,
        text=build_template(data["text"]),
        reply_markup=post_button(data["buttons"])
    )

# ===== BUTTON HANDLER =====
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

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

    # ADD FLOW
    if query.data == "add_vanced":
        context.user_data["add_post"] = "vanced"
        await query.message.reply_text("Enter channel ID")
        return

    if query.data == "add_crunchy":
        context.user_data["add_post"] = "crunchy"
        await query.message.reply_text("Enter channel ID")
        return

    if query.data == "add_footer":
        context.user_data["add_footer"] = True
        await query.message.reply_text("Enter @channel")
        return

    # SHOW
    if query.data == "show_post":
        text = "📡 Channels\n\n"
        for g, ids in channel_groups.items():
            text += f"{g}:\n" + ("\n".join(ids) if ids else "none") + "\n\n"
        await query.message.reply_text(text)
        return

    if query.data == "show_footer":
        text = "\n".join(channel_links) or "No channels"
        await query.message.reply_text(text)
        return

    # NORMAL
    data = pending_messages.get(user_id)

    if not data:
        return

    if query.data == "toggle_notify":
        silent_mode[user_id] = not silent_mode.get(user_id, False)
        await query.edit_message_reply_markup(reply_markup=buttons(user_id))
        return

    if query.data == "add_button":
        data["adding_button"] = True
        data["step"] = "name"
        await query.message.reply_text("Send button name")
        return

    if query.data == "vanced":
        targets = channel_groups["vanced"]
    elif query.data == "crunchy":
        targets = channel_groups["crunchy"]
    else:
        targets = channel_groups["vanced"] + channel_groups["crunchy"]

    for cid in targets:
        await send_post(context, cid, data)

    pending_messages.pop(user_id, None)
    await query.message.delete()

# ===== HELP =====
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Groups:\n- vanced\n- crunchy\n\nUse /panel"
    )

# ===== RUN =====
def run_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("panel", panel))

    app.add_handler(MessageHandler(filters.TEXT, handle_message))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.run_polling()

# ===== MAIN =====
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    threading.Thread(target=ping_self, daemon=True).start()
    run_bot()
