import json
import sqlite3
import time
import aiosqlite
from config import DATABASE_PATH, logger

class DatabaseManager:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path

    async def initialize(self):
        """Creates the database and initializes required tables if they don't exist."""
        logger.info(f"Initializing database at {self.db_path}...")
        async with aiosqlite.connect(self.db_path) as db:
            # Enable WAL mode for high concurrency
            await db.execute("PRAGMA journal_mode=WAL;")
            
            # Check and migrate old flat channels table to grouped channels table
            try:
                async with db.execute("PRAGMA table_info(channels)") as cursor:
                    columns = [row[1] for row in await cursor.fetchall()]
                    if columns and "category" not in columns:
                        logger.info("Dropping old flat channels table to upgrade to grouped category schema...")
                        await db.execute("DROP TABLE channels;")
                        await db.commit()
            except Exception as e:
                logger.debug(f"Channels migration skipped: {e}")

            # Check and migrate posting_queue to add disable_notification column
            try:
                async with db.execute("PRAGMA table_info(posting_queue)") as cursor:
                    columns = [row[1] for row in await cursor.fetchall()]
                    if columns and "disable_notification" not in columns:
                        logger.info("Migrating posting_queue: adding disable_notification column...")
                        await db.execute("ALTER TABLE posting_queue ADD COLUMN disable_notification INTEGER DEFAULT 0;")
                        await db.commit()
            except Exception as e:
                logger.debug(f"Queue migration skipped: {e}")
            
            # Channels Table (grouped by category)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS channels (
                    channel_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    PRIMARY KEY (channel_id, category)
                )
            """)

            # Footer Channels Table (grouped by category)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS footer_channels (
                    channel_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    PRIMARY KEY (channel_id, category)
                )
            """)

            # System Settings Table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            # FSM States Table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS fsm_states (
                    user_id INTEGER PRIMARY KEY,
                    state TEXT NOT NULL,
                    data TEXT DEFAULT '{}',
                    updated_at REAL NOT NULL
                )
            """)

            # Translation Cache Table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS translation_cache (
                    text_hash TEXT PRIMARY KEY,
                    source_lang TEXT NOT NULL,
                    translated_text TEXT NOT NULL,
                    cached_at REAL NOT NULL
                )
            """)

            # Posting Queue Table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS posting_queue (
                    queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    media_file_id TEXT,
                    media_type TEXT NOT NULL,
                    channel_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    retries INTEGER DEFAULT 0,
                    scheduled_at REAL NOT NULL,
                    last_attempt_at REAL,
                    error_message TEXT,
                    disable_notification INTEGER DEFAULT 0
                )
            """)

            await db.commit()

        # Initialize default settings if not exists
        await self.set_setting_default("footer_title", "Join Backup Channel 👇")
        await self.set_setting_default("footer_enabled", "1")
        logger.info("Database initialized successfully.")

    # --- System Settings Operations ---
    async def get_setting(self, key: str, default: str = "") -> str:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT value FROM system_settings WHERE key = ?", (key,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else default

    async def set_setting(self, key: str, value: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO system_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value)
            )
            await db.commit()

    async def set_setting_default(self, key: str, value: str):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT 1 FROM system_settings WHERE key = ?", (key,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    await db.execute("INSERT INTO system_settings (key, value) VALUES (?, ?)", (key, value))
                    await db.commit()

    # --- FSM State Operations ---
    async def get_state(self, user_id: int):
        """Retrieves FSM state and data for a specific user."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT state, data, updated_at FROM fsm_states WHERE user_id = ?", 
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    try:
                        data = json.loads(row[1])
                    except json.JSONDecodeError:
                        data = {}
                    return row[0], data, row[2]
                return None, {}, 0.0

    async def set_state(self, user_id: int, state: str, data: dict):
        """Sets FSM state and serialized data for a specific user, updating timestamp."""
        now = time.time()
        data_str = json.dumps(data)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO fsm_states (user_id, state, data, updated_at) 
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET 
                    state = excluded.state, 
                    data = excluded.data, 
                    updated_at = excluded.updated_at
                """,
                (user_id, state, data_str, now)
            )
            await db.commit()

    async def clear_state(self, user_id: int):
        """Removes the FSM state for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM fsm_states WHERE user_id = ?", (user_id,))
            await db.commit()

    async def cleanup_expired_states(self, expiry_seconds: int):
        """Cleans up abandoned states that have not been updated for the specified duration."""
        cutoff = time.time() - expiry_seconds
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM fsm_states WHERE updated_at < ?", (cutoff,))
            await db.commit()

    # --- Grouped Channel Operations ---
    async def get_channel(self, channel_id: int, category: str):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT channel_id, title, category FROM channels WHERE channel_id = ? AND category = ?",
                (channel_id, category)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "channel_id": row[0],
                        "title": row[1],
                        "category": row[2]
                    }
                return None

    async def add_channel(self, channel_id: int, title: str, category: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO channels (channel_id, title, category)
                VALUES (?, ?, ?)
                ON CONFLICT(channel_id, category) DO UPDATE SET title = excluded.title
                """,
                (channel_id, title, category)
            )
            await db.commit()

    async def delete_channel(self, channel_id: int, category: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM channels WHERE channel_id = ? AND category = ?", (channel_id, category))
            await db.commit()

    async def list_channels_by_category(self, category: str):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT channel_id, title FROM channels WHERE category = ?", (category,)) as cursor:
                rows = await cursor.fetchall()
                return [{"channel_id": row[0], "title": row[1]} for row in rows]

    async def list_all_channels(self):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT channel_id, title, category FROM channels") as cursor:
                rows = await cursor.fetchall()
                return [{"channel_id": row[0], "title": row[1], "category": row[2]} for row in rows]

    # --- Footer Channels Operations ---
    async def add_footer_channel(self, channel_id: str, title: str, category: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO footer_channels (channel_id, title, category)
                VALUES (?, ?, ?)
                ON CONFLICT(channel_id, category) DO UPDATE SET title = excluded.title
                """,
                (channel_id, title, category)
            )
            await db.commit()

    async def delete_footer_channel(self, channel_id: str, category: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM footer_channels WHERE channel_id = ? AND category = ?", (channel_id, category))
            await db.commit()

    async def list_footer_channels_by_category(self, category: str):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT channel_id, title FROM footer_channels WHERE category = ?", (category,)) as cursor:
                rows = await cursor.fetchall()
                return [{"channel_id": row[0], "title": row[1]} for row in rows]

    # --- Translation Cache Operations ---
    async def get_cached_translation(self, text_hash: str):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT source_lang, translated_text FROM translation_cache WHERE text_hash = ?",
                (text_hash,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return row[0], row[1]
                return None

    async def set_cached_translation(self, text_hash: str, source_lang: str, translated_text: str):
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO translation_cache (text_hash, source_lang, translated_text, cached_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(text_hash) DO UPDATE SET
                    source_lang = excluded.source_lang,
                    translated_text = excluded.translated_text,
                    cached_at = excluded.cached_at
                """,
                (text_hash, source_lang, translated_text, now)
            )
            await db.commit()

    async def cleanup_expired_cache(self, days: int):
        cutoff = time.time() - (days * 86400)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM translation_cache WHERE cached_at < ?", (cutoff,))
            await db.commit()

    # --- Posting Queue Operations ---
    async def add_to_queue(
        self, user_id: int, content: dict, media_file_id: str, media_type: str, 
        channel_id: int, delay_seconds: float = 0.0, disable_notification: bool = False
    ):
        scheduled_at = time.time() + delay_seconds
        content_str = json.dumps(content)
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO posting_queue (
                    user_id, content, media_file_id, media_type, channel_id, scheduled_at, status, disable_notification
                )
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (user_id, content_str, media_file_id, media_type, channel_id, scheduled_at, 1 if disable_notification else 0)
            )
            await db.commit()
            return cursor.lastrowid

    async def get_next_queued_items(self, limit: int = 10):
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT queue_id, user_id, content, media_file_id, media_type, channel_id, retries, scheduled_at, disable_notification
                FROM posting_queue
                WHERE status = 'pending' AND scheduled_at <= ?
                ORDER BY scheduled_at ASC
                LIMIT ?
                """,
                (now, limit)
            ) as cursor:
                rows = await cursor.fetchall()
                items = []
                for row in rows:
                    try:
                        content = json.loads(row[2])
                    except json.JSONDecodeError:
                        content = {}
                    items.append({
                        "queue_id": row[0],
                        "user_id": row[1],
                        "content": content,
                        "media_file_id": row[3],
                        "media_type": row[4],
                        "channel_id": row[5],
                        "retries": row[6],
                        "scheduled_at": row[7],
                        "disable_notification": bool(row[8])
                    })
                return items

    async def get_all_pending_queued_items(self, limit: int = 10):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT queue_id, user_id, content, media_file_id, media_type, channel_id, retries, scheduled_at, disable_notification
                FROM posting_queue
                WHERE status = 'pending'
                ORDER BY scheduled_at ASC
                LIMIT ?
                """,
                (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
                items = []
                for row in rows:
                    try:
                        content = json.loads(row[2])
                    except json.JSONDecodeError:
                        content = {}
                    items.append({
                        "queue_id": row[0],
                        "user_id": row[1],
                        "content": content,
                        "media_file_id": row[3],
                        "media_type": row[4],
                        "channel_id": row[5],
                        "retries": row[6],
                        "scheduled_at": row[7],
                        "disable_notification": bool(row[8])
                    })
                return items

    async def update_queue_status(self, queue_id: int, status: str, error_message: str = None, increment_retry: bool = False, scheduled_at: float = None):
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            if increment_retry:
                if scheduled_at is not None:
                    await db.execute(
                        """
                        UPDATE posting_queue
                        SET status = ?, error_message = ?, retries = retries + 1, last_attempt_at = ?, scheduled_at = ?
                        WHERE queue_id = ?
                        """,
                        (status, error_message, now, scheduled_at, queue_id)
                    )
                else:
                    await db.execute(
                        """
                        UPDATE posting_queue
                        SET status = ?, error_message = ?, retries = retries + 1, last_attempt_at = ?
                        WHERE queue_id = ?
                        """,
                        (status, error_message, now, queue_id)
                    )
            else:
                if scheduled_at is not None:
                    await db.execute(
                        """
                        UPDATE posting_queue
                        SET status = ?, error_message = ?, last_attempt_at = ?, scheduled_at = ?
                        WHERE queue_id = ?
                        """,
                        (status, error_message, now, scheduled_at, queue_id)
                    )
                else:
                    await db.execute(
                        """
                        UPDATE posting_queue
                        SET status = ?, error_message = ?, last_attempt_at = ?
                        WHERE queue_id = ?
                        """,
                        (status, error_message, now, queue_id)
                    )
            await db.commit()

    async def cancel_queue_item(self, queue_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE posting_queue SET status = 'cancelled' WHERE queue_id = ? AND status = 'pending'",
                (queue_id,)
            )
            await db.commit()

# Singleton DB instance
db = DatabaseManager()
