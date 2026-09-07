import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

from config import BOT_TOKEN, STATE_CLEANUP_INTERVAL, logger
from database import db
from services.fsm import fsm, States
from services.queue_manager import queue_manager
from handlers.error_handler import global_error_handler, safe_handler, safe_delete_message
from handlers.admin import (
    is_admin, admin_cmd, admin_callback_router,
    handle_admin_text_inputs, handle_admin_forward_inputs
)
from handlers.post_workflow import (
    handle_incoming_post, post_callback_router, handle_custom_buttons_input,
    handle_caption_input, handle_schedule_time_input, handle_web_app_data
)

@safe_handler
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Greets users and provides simple instructions if they are validated administrators."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text(
            "⛔️ <b>Access Denied:</b> This bot is restricted to authorized administrators only.",
            parse_mode="HTML"
        )
        return
    await update.message.reply_text(
        "👋 <b>Welcome to Antigravity Translation Bot!</b>\n\n"
        "To publish a post to your channels, simply send me a Text post, Photo, or Video caption in any language. "
        "I will auto-detect the language, translate it to English, generate a live dynamic preview, and allow you to publish it with footers and custom inline buttons.\n\n"
        "🔧 Type /admin to open the central control panel.",
        parse_mode="HTML"
    )

@safe_handler
async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels any active workflow draft, deletes old preview messages, and clears user FSM state."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    # Delete original command message to keep chat clean
    await safe_delete_message(context.bot, user_id, update.message.message_id)

    _, data = await fsm.get_state(user_id)
    preview_id = data.get("preview_message_id")
    if preview_id:
        await safe_delete_message(context.bot, user_id, preview_id)

    # Completely clear user FSM state persistently
    await fsm.clear_state(user_id)

    info_msg = await context.bot.send_message(
        chat_id=user_id,
        text="🔄 <b>Workflow Reset:</b> Active drafts cleared. State restored to idle.",
        parse_mode="HTML"
    )
    # Self-destruct message after 5 seconds to keep the admin workspace tidy
    await asyncio.sleep(5.0)
    await safe_delete_message(context.bot, user_id, info_msg.message_id)

async def post_init(application) -> None:
    """Asynchronous application post-init hook. Boots database, queue worker, and state sweeps."""
    logger.info("Bot initializing...")
    
    # 1. Wire Telegram Bot instance to backup manager and restore database if available
    from services.backup_manager import backup_manager
    backup_manager.set_bot(application.bot)
    await backup_manager.restore_backup()
    
    # 2. Initialize persistent DB schemas
    await db.initialize()
    
    # 3. Wire bot instance and run non-blocking scheduler worker
    queue_manager.set_bot(application.bot)
    queue_manager.start()

    # 4. Create persistent task for FSM sweeper cleanup loop
    asyncio.create_task(fsm.start_cleanup_loop(STATE_CLEANUP_INTERVAL))

    # 5. Boot keep-alive web server and self-ping thread for Render deployment
    try:
        from services.keep_alive import start_keep_alive
        start_keep_alive()
    except Exception as e:
        logger.error(f"Error starting keep-alive service: {e}", exc_info=True)

    # 6. Start persistent database backup task
    asyncio.create_task(backup_manager.start_backup_loop(120)) # Check every 2 minutes
    
    logger.info("Bot application successfully booted and workers online.")

async def post_shutdown(application) -> None:
    """Asynchronous shutdown hook. Gracefully halts background tasks and DB connections."""
    logger.info("Bot shutting down...")
    await queue_manager.stop()
    logger.info("Shutdown lifecycle complete.")

@safe_handler
async def general_message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Central router for incoming text, photos, and videos.
    Delegates processing based on active user FSM states.
    """
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    state, _ = await fsm.get_state(user_id)

    if state in ["AWAITING_ADD_CHANNEL", "AWAITING_REMOVE_CHANNEL", "AWAITING_SET_FOOTER_TITLE", "AWAITING_ADD_FOOTER_CHANNEL", "AWAITING_REMOVE_FOOTER_CHANNEL"]:
        # Extract forwarded chat/channel safely
        forward_from_chat = getattr(update.message, "forward_from_chat", None)
        if not forward_from_chat and getattr(update.message, "forward_origin", None):
            from telegram import MessageOriginChannel
            if isinstance(update.message.forward_origin, MessageOriginChannel):
                forward_from_chat = update.message.forward_origin.chat

        if forward_from_chat:
            await handle_admin_forward_inputs(update, context)
        else:
            await handle_admin_text_inputs(update, context)
            
    elif state == States.EDITING_BUTTONS:
        await handle_custom_buttons_input(update, context)
        
    elif state == States.EDITING_CAPTION:
        await handle_caption_input(update, context)
        
    elif state == States.AWAITING_SCHEDULE_TIME:
        await handle_schedule_time_input(update, context)
        
    else:
        # Default state: Treat message as a new incoming post draft
        await handle_incoming_post(update, context)

def main():
    """Application entry-point. Builds and starts the Telegram Bot using PTB polling."""
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN is missing! Please configure it in .env file. Exiting...")
        return

    # Build PTB Application with async post_init and post_shutdown hooks
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # 1. Command Handlers
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("admin", admin_cmd))
    application.add_handler(CommandHandler("cancel", cancel_cmd))

    # 2. Callback Query Router Handlers
    # Routes admin button callback clicks
    application.add_handler(CallbackQueryHandler(admin_callback_router, pattern=r"^admin:"))
    # Routes post preview workflow callback clicks
    application.add_handler(CallbackQueryHandler(post_callback_router, pattern=r"^post:"))

    # 3. WebApp Data Return Handler
    application.add_handler(MessageHandler(
        filters.StatusUpdate.WEB_APP_DATA,
        handle_web_app_data
    ))

    # 4. Centralized Message Router (Photos, Videos, Text)
    application.add_handler(MessageHandler(
        filters.TEXT | filters.PHOTO | filters.VIDEO,
        general_message_router
    ))

    # 4. Centralized Framework Global Error Handler
    application.add_error_handler(global_error_handler)

    # Start Polling with clean thread loops
    logger.info("Bot starting polling loop...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
