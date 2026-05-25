import asyncio
import time
import functools
from typing import Callable, Any, Optional
from telegram import Update, Bot
from telegram.ext import ContextTypes
from telegram.error import TelegramError, BadRequest, Forbidden, TimedOut, NetworkError

from config import logger, ADMIN_IDS

# Global click lock to prevent fast-callback/callback spam clicking
# Format: {user_id: last_click_timestamp}
_callback_debounces = {}
_debounce_lock = asyncio.Lock()

def safe_handler(func: Callable):
    """
    Decorator to wrap any Telegram handler in a comprehensive try-except block.
    Ensures that uncaught handler errors never crash the bot.
    """
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        try:
            return await func(update, context, *args, **kwargs)
        except Exception as e:
            logger.error(f"Uncaught exception in handler '{func.__name__}': {e}", exc_info=True)
            # Notify user gracefully
            if update.effective_user:
                try:
                    await context.bot.send_message(
                        chat_id=update.effective_user.id,
                        text="⚠️ <b>A temporary server error occurred.</b> Please try again or type /cancel.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
    return wrapper

def safe_callback(func: Callable):
    """
    Decorator specifically for callback query handlers to:
    1. Debounce rapid clicks/spam (discards clicks closer than 0.5s).
    2. Auto-answer callback queries to clear Telegram spinners.
    3. Recover gracefully if the original message was deleted or stale.
    """
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        query = update.callback_query
        if not query:
            return

        user_id = update.effective_user.id
        now = time.time()

        # 1. Debounce checking
        async with _debounce_lock:
            last_click = _callback_debounces.get(user_id, 0.0)
            if now - last_click < 0.5:
                # Spam click detected, answer silently and discard
                try:
                    await query.answer("Slow down! You're clicking too fast.", show_alert=False)
                except Exception:
                    pass
                return
            _callback_debounces[user_id] = now

        # 2. Execute callback query processing
        try:
            # Answer the query immediately to dismiss the loading animation
            try:
                await query.answer()
            except Exception:
                pass

            return await func(update, context, *args, **kwargs)

        except BadRequest as e:
            err_msg = str(e).lower()
            if "message to edit not found" in err_msg or "message is not modified" in err_msg:
                logger.warning(f"Callback edit error in '{func.__name__}' (expected behaviour): {e}")
            elif "query is too old" in err_msg:
                logger.warning(f"Old callback query in '{func.__name__}': {e}")
                try:
                    await query.answer("This menu has expired. Please launch a new one.", show_alert=True)
                except Exception:
                    pass
            else:
                logger.error(f"Telegram BadRequest in callback handler '{func.__name__}': {e}", exc_info=True)
        except Forbidden as e:
            logger.warning(f"Bot blocked in callback handler '{func.__name__}': {e}")
        except Exception as e:
            logger.error(f"Error in callback handler '{func.__name__}': {e}", exc_info=True)
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="⚠️ <b>An error occurred while processing your selection.</b> Please restart the flow.",
                    parse_mode="HTML"
                )
            except Exception:
                pass
    return wrapper

# --- Safe Message API Operations ---

async def safe_send_message(bot: Bot, chat_id: int, text: str, **kwargs) -> Optional[Any]:
    """Safely sends a message, retrying on temporary network issues and returning the message object."""
    for attempt in range(3):
        try:
            return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except (TimedOut, NetworkError) as e:
            logger.warning(f"Network exception on send_message (attempt {attempt+1}): {e}")
            await asyncio.sleep(1.0 * (attempt + 1))
        except BadRequest as e:
            logger.error(f"BadRequest when sending message to {chat_id}: {e}")
            break
        except Forbidden as e:
            logger.warning(f"Bot blocked when sending message to {chat_id}: {e}")
            break
        except Exception as e:
            logger.error(f"Unexpected error in safe_send_message: {e}", exc_info=True)
            break
    return None

async def safe_edit_message_text(bot: Bot, chat_id: int, message_id: int, text: str, **kwargs) -> bool:
    """
    Safely edits a message's text, suppressing 'Message is not modified' 
    and returning True if the edit was successful, or False otherwise.
    """
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, **kwargs)
        return True
    except BadRequest as e:
        err_msg = str(e).lower()
        if "message is not modified" in err_msg:
            # Redundant edit, ignore and count as success
            return True
        elif "message to edit not found" in err_msg or "chat not found" in err_msg:
            logger.warning(f"Attempted to edit non-existent message #{message_id} in chat {chat_id}.")
            return False
        else:
            logger.error(f"BadRequest editing message #{message_id}: {e}")
            return False
    except Exception as e:
        logger.error(f"Unexpected error in safe_edit_message_text: {e}", exc_info=True)
        return False

async def safe_edit_message_caption(bot: Bot, chat_id: int, message_id: int, caption: str, **kwargs) -> bool:
    """Safely edits a media caption, suppressing common non-modified and deleted exceptions."""
    try:
        await bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=caption, **kwargs)
        return True
    except BadRequest as e:
        err_msg = str(e).lower()
        if "message is not modified" in err_msg:
            return True
        elif "message to edit not found" in err_msg:
            logger.warning(f"Attempted to edit caption of non-existent message #{message_id} in chat {chat_id}.")
            return False
        else:
            logger.error(f"BadRequest editing caption of message #{message_id}: {e}")
            return False
    except Exception as e:
        logger.error(f"Unexpected error in safe_edit_message_caption: {e}", exc_info=True)
        return False

async def safe_delete_message(bot: Bot, chat_id: int, message_id: int) -> bool:
    """Safely deletes a message, catching and suppressing exceptions if the message is already deleted."""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        return True
    except BadRequest as e:
        err_msg = str(e).lower()
        if "message to delete not found" in err_msg or "message can't be deleted" in err_msg:
            # Already deleted or too old, treat as successfully gone
            return True
        logger.warning(f"Failed to delete message #{message_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error deleting message #{message_id}: {e}", exc_info=True)
        return False

# --- Global Framework Exception Handler ---

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global logging handler registered inside python-telegram-bot."""
    logger.error("Exception occurred while handling an update:", exc_info=context.error)

    # Avoid spamming admins on network timeouts, interruptions, or getUpdates polling conflicts
    from telegram.error import Conflict
    if isinstance(context.error, (Conflict, TimedOut, NetworkError)):
        return

    # Convert object to string safely
    update_str = str(update)[:1000]
    
    # Notify Admin if possible
    if ADMIN_IDS:
        for admin_id in ADMIN_IDS:
            try:
                # Format a clean crash warning to admin without overflowing message lengths
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"⚠️ <b>CRITICAL SYSTEM ERROR</b>\n\n"
                        f"• <b>Error:</b> <code>{str(context.error)[:400]}</code>\n\n"
                        f"<i>Check system logs for the full stack trace. The bot has successfully intercepted this error and remains active.</i>"
                    ),
                    parse_mode="HTML"
                )
            except Exception:
                pass
