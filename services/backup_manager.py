import os
import time
import hashlib
import asyncio
from config import logger, DATABASE_PATH

# Chat/Channel ID where the database backups will be sent and pinned
BACKUP_CHAT_ID_RAW = os.getenv("BACKUP_CHAT_ID", "").strip()

def parse_chat_id(raw_id: str):
    """Converts numeric channel/chat strings into int, keeping username strings intact."""
    if not raw_id:
        return None
    try:
        return int(raw_id)
    except ValueError:
        return raw_id

BACKUP_CHAT_ID = parse_chat_id(BACKUP_CHAT_ID_RAW)

class BackupManager:
    def __init__(self):
        self.last_backup_mtime = 0.0
        self.last_backup_hash = ""
        self.restored_successfully = False
        self.bot = None

    def set_bot(self, bot):
        """Passes the Telegram Bot instance to the backup manager."""
        self.bot = bot

    def _compute_hash(self) -> str:
        """Computes SHA-256 hash of the database file if it exists."""
        if not os.path.exists(DATABASE_PATH):
            return ""
        try:
            with open(DATABASE_PATH, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception as e:
            logger.error(f"Failed to compute DB hash: {e}")
            return ""

    def sync_current_hash(self):
        """Updates internal hash tracker to match current DB content without triggering backup."""
        self.last_backup_hash = self._compute_hash()
        if os.path.exists(DATABASE_PATH):
            self.last_backup_mtime = os.path.getmtime(DATABASE_PATH)

    async def restore_backup(self) -> bool:
        """
        Retrieves the latest pinned bot.db document from the backup channel on startup.
        Downloads it to DATABASE_PATH before the DB manager initializes.
        """
        if not BACKUP_CHAT_ID:
            logger.info("BACKUP_CHAT_ID not configured. Skipping persistent database restore.")
            return False

        if not self.bot:
            logger.error("BackupManager bot instance is not set. Cannot restore backup.")
            return False

        try:
            logger.info(f"Checking for persistent database backup in chat/channel: {BACKUP_CHAT_ID}...")
            
            # Fetch chat info to get the latest pinned message
            chat = await self.bot.get_chat(BACKUP_CHAT_ID)
            pinned = chat.pinned_message
            
            if not pinned or not pinned.document:
                logger.info("No pinned database backup document found in backup chat/channel.")
                return False

            doc = pinned.document
            if not doc.file_name or not doc.file_name.endswith(".db"):
                logger.warning(f"Pinned document '{doc.file_name}' is not a SQLite database file. Skipping restore.")
                return False

            if doc.file_size == 0:
                logger.warning("Pinned document file size is 0 bytes. Skipping restore of empty file.")
                return False

            logger.info(f"Found pinned database backup '{doc.file_name}' (size: {doc.file_size} bytes). Downloading...")
            
            # Ensure the database directory exists
            os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
            
            # Download file to path
            file = await self.bot.get_file(doc.file_id)
            await file.download_to_drive(DATABASE_PATH)
            
            logger.info("Database successfully restored from Telegram backup!")
            
            self.sync_current_hash()
            self.restored_successfully = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to restore database backup from Telegram: {e}", exc_info=True)
            return False

    async def perform_backup(self, force: bool = False) -> bool:
        """
        Checks if the database has been modified since the last backup.
        Flushes WAL to disk, calculates SHA-256 hash, and if modified,
        uploads to the backup channel and pins it.
        """
        if not BACKUP_CHAT_ID:
            return False

        if not self.bot:
            return False

        if not os.path.exists(DATABASE_PATH):
            return False

        try:
            # 1. Flush SQLite WAL to ensure bot.db is completely up-to-date
            from database import db
            await db.checkpoint()

            # 2. Compute current SHA-256 hash
            current_hash = self._compute_hash()
            if not current_hash:
                return False

            # 3. Skip if hash is unchanged and backup is not forced
            if not force and current_hash == self.last_backup_hash:
                logger.debug("Database hash unchanged. Skipping backup.")
                return False

            # Add a small delay to ensure SQLite file locks are released cleanly
            await asyncio.sleep(0.5)
            
            logger.info(f"Database modification detected (hash: {current_hash[:8]}...). Uploading backup to chat/channel: {BACKUP_CHAT_ID}...")
            
            # Send file to backup channel
            with open(DATABASE_PATH, "rb") as db_file:
                msg = await self.bot.send_document(
                    chat_id=BACKUP_CHAT_ID,
                    document=db_file,
                    filename=os.path.basename(DATABASE_PATH),
                    caption=(
                        f"📂 <b>Bot Database Backup</b>\n\n"
                        f"• Hash: <code>{current_hash[:10]}</code>\n"
                        f"• Timestamp: <code>{time.strftime('%Y-%m-%d %H:%M:%S')}</code>"
                    ),
                    parse_mode="HTML"
                )
            
            # Pin the new backup message silently
            await self.bot.pin_chat_message(
                chat_id=BACKUP_CHAT_ID,
                message_id=msg.message_id,
                disable_notification=True
            )
            
            self.last_backup_hash = current_hash
            self.last_backup_mtime = os.path.getmtime(DATABASE_PATH)
            logger.info("Database backup successfully uploaded and pinned.")
            return True
            
        except Exception as e:
            logger.error(f"Failed to perform database backup to Telegram: {e}", exc_info=True)
            return False

    async def start_backup_loop(self, interval_seconds: int = 120):
        """Background loop that periodically checks for changes and triggers backups."""
        if not BACKUP_CHAT_ID:
            logger.warning("BACKUP_CHAT_ID is empty. Telegram persistent backups are DISABLED.")
            return

        logger.info(f"Telegram persistent backup loop started (checking every {interval_seconds}s)...")
        while True:
            await asyncio.sleep(interval_seconds)
            await self.perform_backup()

# Singleton instance
backup_manager = BackupManager()

