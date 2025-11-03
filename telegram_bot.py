from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CommandHandler
import os
# === Configuration ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_IDS = [
    "-1003052492544",  # Add more channel IDs here
]

# === Handlers ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hi! Send me any message, photo, or video — I’ll post it to all connected channels.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = Bot(token=BOT_TOKEN)

    # If message has text
    if update.message.text:
        text = update.message.text
        for cid in CHANNEL_IDS:
            try:
                await bot.send_message(chat_id=cid, text=text)
                print(f"✅ Sent text to {cid}")
            except Exception as e:
                print(f"❌ Failed to send text to {cid}: {e}")

    # If message has photo
    elif update.message.photo:
        photo_id = update.message.photo[-1].file_id
        caption = update.message.caption or ""
        for cid in CHANNEL_IDS:
            try:
                await bot.send_photo(chat_id=cid, photo=photo_id, caption=caption)
                print(f"✅ Sent photo to {cid}")
            except Exception as e:
                print(f"❌ Failed to send photo to {cid}: {e}")

    # If message has video
    elif update.message.video:
        video_id = update.message.video.file_id
        caption = update.message.caption or ""
        for cid in CHANNEL_IDS:
            try:
                await bot.send_video(chat_id=cid, video=video_id, caption=caption)
                print(f"✅ Sent video to {cid}")
            except Exception as e:
                print(f"❌ Failed to send video to {cid}: {e}")

    else:
        await update.message.reply_text("⚠️ Unsupported message type. Please send text, photo, or video.")

    await update.message.reply_text("✅ Message sent to all channels!")

# === App Setup ===
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, broadcast))

# === Run the bot ===
print("🚀 Bot is running... send it a message, photo, or video in Telegram!")
app.run_polling()



