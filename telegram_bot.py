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

# ===== WEB SERVER =====
app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Bot Running"

def run_web():
    port = int(os.getenv("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

# ===== KEEP ALIVE =====
def ping():
    while True:
        if SELF_URL:
            try:
                requests.get(SELF_URL)
            except:
                pass
        time.sleep(300)

# ===== TEMPLATE (NO FOOTER) =====
def build_template(text):
    return f"👇👇👇\n\n{text}".strip()

# ===== BUTTONS =====
def preview_buttons(user_id):
    silent = silent_mode.get(user_id, False)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔕 Silent ON" if silent else "🔔 Silent OFF", callback_data="toggle")],
        [InlineKeyboardButton("➕ Add Button", callback_data="add_btn")],
        [InlineKeyboardButton("✏ Edit", callback_data="edit")],
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

# ===== ADMIN PANEL =====
def panel_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Post Channels", callback_data="p_post")],
        [InlineKeyboardButton("❌ Close", callback_data="p_close")]
    ])

def panel_post():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Vanced", callback_data="add_v")],
        [InlineKeyboardButton("➕ Add Crunchy", callback_data="add_c")],
        [InlineKeyboardButton("📋 Show Channels", callback_data="show_p")],
        [InlineKeyboardButton("🔙 Back", callback_data="p_back")]
    ])

# ===== COMMANDS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return
    await update.message.reply_text("Send post content")

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚙️ Admin Panel", reply_markup=panel_menu())

# ===== MESSAGE HANDLER =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    uid = update.effective_user.id
    if uid not in ALLOWED_USERS:
        return

    text = update.message.text or ""

    # PANEL INPUT
    if context.user_data.get("add_post"):
        group = context.user_data.pop("add_post")

        if not text.startswith("-100"):
            await update.message.reply_text("❌ Invalid ID. Use -100xxxx")
            return

        if text not in channel_groups[group]:
            channel_groups[group].append(text)

        await update.message.reply_text(f"✅ Added to {group}")
        return

    # BUTTON CREATION FLOW
    if uid in pending_messages:
        data = pending_messages[uid]

        if data.get("adding"):
            if data["step"] == "name":
                data["temp"] = text
                data["step"] = "link"
                await update.message.reply_text("Send button link")
                return
            else:
                data["buttons"].append({"name": data["temp"], "link": text})
                data["adding"] = False
                await update.message.reply_text("✅ Button added", reply_markup=preview_buttons(uid))
                return

    # NEW POST
    pending_messages[uid] = {
        "text": text,
        "buttons": [],
        "adding": False,
        "step": "name"
    }

    await update.message.reply_text(build_template(text), reply_markup=preview_buttons(uid))

# ===== SEND =====
async def send(context, cid, data):
    await context.bot.send_message(
        chat_id=cid,
        text=build_template(data["text"]),
        reply_markup=build_post_buttons(data["buttons"])
    )

# ===== CALLBACK HANDLER =====
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    # PANEL NAV
    if q.data == "p_post":
        await q.edit_message_text("📡 Post Channels", reply_markup=panel_post()); return
    if q.data == "p_back":
        await q.edit_message_text("⚙️ Admin Panel", reply_markup=panel_menu()); return
    if q.data == "p_close":
        await q.message.delete(); return

    # PANEL ACTIONS
    if q.data == "add_v":
        context.user_data["add_post"] = "vanced"
        await q.message.reply_text("Enter channel ID (-100...)"); return

    if q.data == "add_c":
        context.user_data["add_post"] = "crunchy"
        await q.message.reply_text("Enter channel ID (-100...)"); return

    if q.data == "show_p":
        text = "📡 Channels:\n\n"
        for g, ids in channel_groups.items():
            text += f"{g.upper()}:\n"
            text += ("\n".join(ids) if ids else "none") + "\n\n"
        await q.message.reply_text(text); return

    # NORMAL FLOW
    if uid not in pending_messages:
        return

    data = pending_messages[uid]

    # SMART CANCEL
    if q.data == "cancel":
        pending_messages.pop(uid, None)
        context.user_data.clear()
        await q.message.delete()
        await q.message.reply_text("❌ Cancelled")
        return

    if q.data == "toggle":
        silent_mode[uid] = not silent_mode.get(uid, False)
        await q.edit_message_reply_markup(reply_markup=preview_buttons(uid))
        return

    if q.data == "add_btn":
        data["adding"] = True
        data["step"] = "name"
        await q.message.reply_text("Send button name")
        return

    if q.data == "edit":
        await q.message.reply_text("Send new text")
        return

    # SEND
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
    app.add_handler(CommandHandler("panel", panel))

    app.add_handler(MessageHandler(filters.TEXT, handle_message))
    app.add_handler(CallbackQueryHandler(callback))

    print("Bot running...")
    app.run_polling()

# ===== MAIN =====
if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    threading.Thread(target=ping, daemon=True).start()
    run()