import os
import json
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
DATA_FILE = "data.json"

# ===== LOAD / SAVE =====
def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "groups": {"vanced": [], "crunchy": []},
            "footer": {
                "enabled": True,
                "title": "Join Backup Channel 👇",
                "channels": []
            }
        }
    with open(DATA_FILE) as f:
        return json.load(f)

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

data = load_data()

pending_messages = {}
silent_mode = {}

# ===== TEMPLATE =====
def build_template(text):
    msg = f"👇👇👇\n\n{text}\n\n"

    footer = data["footer"]
    if footer["enabled"] and footer["channels"]:
        msg += f"{footer['title']}\n\n"
        for ch in footer["channels"]:
            msg += f"👉 {ch}\n"

    return msg.strip()

# ===== BUTTONS =====
def preview_buttons(uid):
    footer = data["footer"]["enabled"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔔 Toggle Silent", callback_data="toggle")],
        [InlineKeyboardButton("📺 Footer ON" if footer else "📺 Footer OFF", callback_data="toggle_footer")],
        [InlineKeyboardButton("➕ Add Button", callback_data="add_btn")],
        [
            InlineKeyboardButton("🎮 Vanced", callback_data="vanced"),
            InlineKeyboardButton("🍿 Crunchy", callback_data="crunchy")
        ],
        [InlineKeyboardButton("🚀 Send Both", callback_data="both")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])

def post_buttons(btns):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(b["name"], url=b["link"])] for b in btns
    ]) if btns else None

# ===== PANEL =====
def panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Post Channels", callback_data="p_post")],
        [InlineKeyboardButton("📺 Footer", callback_data="p_footer")],
        [InlineKeyboardButton("❌ Close", callback_data="close")]
    ])

def post_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Vanced", callback_data="add_v")],
        [InlineKeyboardButton("➕ Add Crunchy", callback_data="add_c")],
        [InlineKeyboardButton("➖ Remove Vanced", callback_data="rem_v")],
        [InlineKeyboardButton("➖ Remove Crunchy", callback_data="rem_c")],
        [InlineKeyboardButton("📋 Show", callback_data="show_p")],
        [InlineKeyboardButton("🔙 Back", callback_data="back")]
    ])

def footer_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏ Set Title", callback_data="set_title")],
        [InlineKeyboardButton("➕ Add Channel", callback_data="add_footer")],
        [InlineKeyboardButton("➖ Remove Channel", callback_data="rem_footer")],
        [InlineKeyboardButton("📋 Show Footer", callback_data="show_footer")],
        [InlineKeyboardButton("🔙 Back", callback_data="back")]
    ])

# ===== COMMANDS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ALLOWED_USERS:
        return
    await update.message.reply_text("Send post")

async def panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚙️ Panel", reply_markup=panel())

# ===== MESSAGE =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ALLOWED_USERS:
        return

    text = update.message.text or ""

    # ADD/REMOVE CHANNELS
    if context.user_data.get("add"):
        g = context.user_data.pop("add")
        data["groups"][g].append(text)
        save_data()
        await update.message.reply_text("Added")
        return

    if context.user_data.get("remove"):
        g = context.user_data.pop("remove")
        if text in data["groups"][g]:
            data["groups"][g].remove(text)
            save_data()
        await update.message.reply_text("Removed")
        return

    # FOOTER
    if context.user_data.get("title"):
        data["footer"]["title"] = text
        context.user_data.clear()
        save_data()
        await update.message.reply_text("Title set")
        return

    if context.user_data.get("add_footer"):
        data["footer"]["channels"].append(text)
        context.user_data.clear()
        save_data()
        await update.message.reply_text("Added")
        return

    if context.user_data.get("rem_footer"):
        if text in data["footer"]["channels"]:
            data["footer"]["channels"].remove(text)
        context.user_data.clear()
        save_data()
        await update.message.reply_text("Removed")
        return

    # BUTTON FLOW
    if uid in pending_messages:
        d = pending_messages[uid]
        if d.get("add_btn"):
            if "name" not in d:
                d["name"] = text
                await update.message.reply_text("Send link")
            else:
                d["buttons"].append({"name": d["name"], "link": text})
                d.pop("name")
                d["add_btn"] = False
                await update.message.reply_text("Added", reply_markup=preview_buttons(uid))
            return

    pending_messages[uid] = {"text": text, "buttons": []}
    await update.message.reply_text(build_template(text), reply_markup=preview_buttons(uid))

# ===== CALLBACK =====
async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "p_post":
        await q.edit_message_text("Post", reply_markup=post_panel()); return
    if q.data == "p_footer":
        await q.edit_message_text("Footer", reply_markup=footer_panel()); return
    if q.data == "back":
        await q.edit_message_text("Panel", reply_markup=panel()); return
    if q.data == "close":
        await q.message.delete(); return

    if q.data == "add_v":
        context.user_data["add"] = "vanced"
        await q.message.reply_text("Send ID"); return
    if q.data == "add_c":
        context.user_data["add"] = "crunchy"
        await q.message.reply_text("Send ID"); return

    if q.data == "rem_v":
        context.user_data["remove"] = "vanced"
        await q.message.reply_text("Send ID"); return
    if q.data == "rem_c":
        context.user_data["remove"] = "crunchy"
        await q.message.reply_text("Send ID"); return

    if q.data == "show_p":
        txt = str(data["groups"])
        await q.message.reply_text(txt); return

    if q.data == "set_title":
        context.user_data["title"] = True
        await q.message.reply_text("Send title"); return

    if q.data == "add_footer":
        context.user_data["add_footer"] = True
        await q.message.reply_text("Send @channel"); return

    if q.data == "rem_footer":
        context.user_data["rem_footer"] = True
        await q.message.reply_text("Send @channel"); return

    if q.data == "show_footer":
        await q.message.reply_text(str(data["footer"])); return

    if uid not in pending_messages:
        return

    d = pending_messages[uid]

    if q.data == "cancel":
        pending_messages.pop(uid)
        context.user_data.clear()
        await q.message.delete()
        return

    if q.data == "toggle_footer":
        data["footer"]["enabled"] = not data["footer"]["enabled"]
        save_data()
        await q.edit_message_reply_markup(reply_markup=preview_buttons(uid))
        return

    if q.data == "add_btn":
        d["add_btn"] = True
        await q.message.reply_text("Send button name")
        return

    targets = []
    if q.data == "vanced":
        targets = data["groups"]["vanced"]
    elif q.data == "crunchy":
        targets = data["groups"]["crunchy"]
    else:
        targets = data["groups"]["vanced"] + data["groups"]["crunchy"]

    for cid in targets:
        await context.bot.send_message(
            chat_id=cid,
            text=build_template(d["text"]),
            reply_markup=post_buttons(d["buttons"])
        )

    pending_messages.pop(uid)
    await q.message.delete()

# ===== RUN =====
def run():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", panel_cmd))

    app.add_handler(MessageHandler(filters.TEXT, handle_message))
    app.add_handler(CallbackQueryHandler(callback))

    app.run_polling()

# ===== MAIN =====
if __name__ == "__main__":
    run()
