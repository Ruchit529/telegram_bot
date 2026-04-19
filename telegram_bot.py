import os, json
from telegram import *
from telegram.ext import *

BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USERS = {7173549132, 7050803817}

DATA_FILE = "data.json"
pending_messages = {}

channel_groups = {"vanced": [], "crunchy": []}
footer_enabled = True

footers = {
    "vanced": {"title": "Join Vanced 👇", "channels": []},
    "crunchy": {"title": "Join Crunchy 👇", "channels": []},
}

# ===== LOAD / SAVE =====
def load_data():
    global channel_groups, footers, footer_enabled
    try:
        with open(DATA_FILE) as f:
            d = json.load(f)
            channel_groups = d.get("groups", channel_groups)
            footers.update(d.get("footers", {}))
            footer_enabled = d.get("footer_enabled", True)
    except:
        save_data()

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump({
            "groups": channel_groups,
            "footers": footers,
            "footer_enabled": footer_enabled
        }, f, indent=4)

# ===== TEMPLATE =====
def build_template(text, group):
    msg = f"👇👇👇\n\n{text}\n\n"
    if footer_enabled:
        f = footers[group]
        if f["channels"]:
            msg += f"{f['title']}\n\n"
            for ch in f["channels"]:
                msg += f"👉 {ch}\n"
    return msg.strip()

# ===== BUTTON BUILDER =====
def build_buttons(data):
    rows, row = [], []
    for i, (n, l) in enumerate(data.get("buttons", []), 1):
        row.append(InlineKeyboardButton(n, url=l))
        if i % 2 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows) if rows else None

# ===== PREVIEW =====
def preview_buttons():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏ Edit", callback_data="edit"),
            InlineKeyboardButton("➕ Button", callback_data="add_btn")
        ],
        [
            InlineKeyboardButton(
                "📺 ON" if footer_enabled else "📺 OFF",
                callback_data="toggle_footer"
            )
        ],
        [
            InlineKeyboardButton("🎮 Vanced", callback_data="send_v"),
            InlineKeyboardButton("🍿 Crunchy", callback_data="send_c"),
        ],
        [InlineKeyboardButton("🚀 Both", callback_data="send_b")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])

# ===== PANEL =====
async def panel(update: Update, context):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Post Channels", callback_data="panel_post")],
        [InlineKeyboardButton("📺 Vanced Footer", callback_data="panel_footer_v")],
        [InlineKeyboardButton("🍿 Crunchy Footer", callback_data="panel_footer_c")],
    ])
    await update.message.reply_text("⚙ Control Panel", reply_markup=kb)

# ===== MESSAGE =====
async def handle_message(update: Update, context):
    uid = update.effective_user.id
    if uid not in ALLOWED_USERS:
        return

    msg = update.message
    text = msg.text or msg.caption or ""

    # ===== ADD BUTTON =====
    if context.user_data.get("add_btn"):
        context.user_data.pop("add_btn")

        try:
            n, l = text.split(" - ", 1)
        except:
            return await msg.reply_text("❌ Use: Name - Link")

        pending_messages[uid]["buttons"].append((n, l))
        return await msg.reply_text("✅ Button added")

    # ===== FOOTER INPUT =====
    if context.user_data.get("edit_footer_title"):
        g = context.user_data.pop("edit_footer_title")
        footers[g]["title"] = text
        save_data()
        return await msg.reply_text("✅ Title updated")

    if context.user_data.get("add_footer"):
        g = context.user_data.pop("add_footer")
        if text not in footers[g]["channels"]:
            footers[g]["channels"].append(text)
            save_data()
            return await msg.reply_text("✅ Footer added")
        return await msg.reply_text("⚠ Already exists")

    if context.user_data.get("remove_footer"):
        g = context.user_data.pop("remove_footer")
        if text in footers[g]["channels"]:
            footers[g]["channels"].remove(text)
            save_data()
            return await msg.reply_text("✅ Removed")
        return await msg.reply_text("❌ Not found")

    # ===== POST CHANNEL INPUT =====
    if context.user_data.get("add_post"):
        g = context.user_data.pop("add_post")
        channel_groups[g].append(text)
        save_data()
        return await msg.reply_text("✅ Added")

    if context.user_data.get("remove_post"):
        g = context.user_data.pop("remove_post")
        if text in channel_groups[g]:
            channel_groups[g].remove(text)
            save_data()
            return await msg.reply_text("✅ Removed")
        return await msg.reply_text("❌ Not found")

    # ===== NEW POST =====
    media, fid = None, None

    if msg.photo:
        media, fid = "photo", msg.photo[-1].file_id
    elif msg.video:
        media, fid = "video", msg.video.file_id

    pending_messages[uid] = {
        "text": text,
        "media": media,
        "file_id": fid,
        "buttons": []
    }

    if media == "photo":
        await msg.reply_photo(fid, caption=text, reply_markup=preview_buttons())
    elif media == "video":
        await msg.reply_video(fid, caption=text, reply_markup=preview_buttons())
    else:
        await msg.reply_text(text, reply_markup=preview_buttons())

# ===== SEND =====
async def send(context, cid, data, g):
    t = build_template(data["text"], g)
    m = build_buttons(data)

    if data["media"] == "photo":
        await context.bot.send_photo(cid, data["file_id"], caption=t, reply_markup=m)
    elif data["media"] == "video":
        await context.bot.send_video(cid, data["file_id"], caption=t, reply_markup=m)
    else:
        await context.bot.send_message(cid, t, reply_markup=m)

# ===== CALLBACK =====
async def callback(update: Update, context):
    global footer_enabled

    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    # ===== BUTTON =====
    if q.data == "add_btn":
        context.user_data["add_btn"] = True
        return await q.message.reply_text("Send: Name - Link")

    # ===== FOOTER TOGGLE =====
    if q.data == "toggle_footer":
        footer_enabled = not footer_enabled
        save_data()
        return await q.edit_message_reply_markup(reply_markup=preview_buttons())

    # ===== PANEL POST =====
    if q.data == "panel_post":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 Vanced", callback_data="post_v"),
             InlineKeyboardButton("🍿 Crunchy", callback_data="post_c")],
            [InlineKeyboardButton("📋 Show All", callback_data="list_all")]
        ])
        return await q.message.reply_text("📡 Post Channels", reply_markup=kb)

    if q.data in ["post_v", "post_c"]:
        g = "vanced" if q.data == "post_v" else "crunchy"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add", callback_data=f"add_post_{g}")],
            [InlineKeyboardButton("➖ Remove", callback_data=f"remove_post_{g}")]
        ])
        return await q.message.reply_text(f"{g.upper()} Channels", reply_markup=kb)

    if q.data == "list_all":
        v = "\n".join(channel_groups["vanced"]) or "Empty"
        c = "\n".join(channel_groups["crunchy"]) or "Empty"
        return await q.message.reply_text(f"🎮 VANCED:\n{v}\n\n🍿 CRUNCHY:\n{c}")

    # ===== FOOTER PANEL =====
    if q.data == "panel_footer_v":
        g = "vanced"
    elif q.data == "panel_footer_c":
        g = "crunchy"
    else:
        g = None

    if g:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏ Title", callback_data=f"title_{g}")],
            [InlineKeyboardButton("➕ Add", callback_data=f"add_footer_{g}")],
            [InlineKeyboardButton("➖ Remove", callback_data=f"remove_footer_{g}")],
            [InlineKeyboardButton("📋 List", callback_data=f"list_footer_{g}")]
        ])
        return await q.message.reply_text(f"{g.upper()} Footer", reply_markup=kb)

    # ===== FOOTER ACTION =====
    if q.data.startswith("title_"):
        context.user_data["edit_footer_title"] = q.data.split("_")[1]
        return await q.message.reply_text("Send title")

    if q.data.startswith("add_footer_"):
        context.user_data["add_footer"] = q.data.split("_")[2]
        return await q.message.reply_text("Send channel")

    if q.data.startswith("remove_footer_"):
        context.user_data["remove_footer"] = q.data.split("_")[2]
        return await q.message.reply_text("Send channel to remove")

    if q.data.startswith("list_footer_"):
        g = q.data.split("_")[2]
        return await q.message.reply_text("\n".join(footers[g]["channels"]) or "Empty")

    # ===== POST ACTION =====
    if q.data.startswith("add_post_"):
        context.user_data["add_post"] = q.data.split("_")[2]
        return await q.message.reply_text("Send channel ID")

    if q.data.startswith("remove_post_"):
        context.user_data["remove_post"] = q.data.split("_")[2]
        return await q.message.reply_text("Send channel ID")

    # ===== SEND =====
    if uid not in pending_messages:
        return

    d = pending_messages[uid]

    if q.data == "send_v":
        for c in channel_groups["vanced"]:
            await send(context, c, d, "vanced")

    elif q.data == "send_c":
        for c in channel_groups["crunchy"]:
            await send(context, c, d, "crunchy")

    elif q.data == "send_b":
        for c in channel_groups["vanced"]:
            await send(context, c, d, "vanced")
        for c in channel_groups["crunchy"]:
            await send(context, c, d, "crunchy")

    elif q.data == "cancel":
        pending_messages.pop(uid, None)
        return await q.message.delete()

    pending_messages.pop(uid, None)
    await q.message.delete()

# ===== RUN =====
def run():
    load_data()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    app.add_handler(CallbackQueryHandler(callback))
    app.run_polling()

if __name__ == "__main__":
    run()