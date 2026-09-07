import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# Bot Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    logging.warning("BOT_TOKEN is not defined in the environment or .env file.")

# Admins: Comma-separated list of Telegram User IDs
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = []
if ADMIN_IDS_RAW:
    try:
        ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip()]
    except ValueError:
        logging.error("Failed to parse ADMIN_IDS. Must be a comma-separated list of integers.")

# Database Configuration
DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "bot.db"))

# Translation Settings
DEFAULT_TARGET_LANGUAGE = "en"
TRANSLATION_RATE_LIMIT = 0.2  # Min seconds between translation requests for real-time performance
TRANSLATION_CACHE_EXPIRY_DAYS = 30

# Queue & Retry Settings
QUEUE_CHECK_INTERVAL = 1.0  # poll queue every second
MAX_RETRIES = 5
RETRY_INITIAL_DELAY = 2.0  # seconds
RETRY_MAX_DELAY = 60.0  # seconds
TELEGRAM_FLOOD_LIMIT_PER_CHAT = 1.0  # seconds between sends to the same chat
TELEGRAM_FLOOD_LIMIT_GLOBAL = 0.033  # seconds between sends globally (~30 sends/sec)

# State Expiration & Cleanup
STATE_CLEANUP_INTERVAL = 300  # run cleanup every 5 minutes (300 seconds)
STATE_EXPIRY_SECONDS = 3600  # expire inactive states after 1 hour (3600 seconds)
PREVIEW_EXPIRY_SECONDS = 1800  # expire old preview sessions after 30 minutes

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(BASE_DIR / "bot.log", encoding="utf-8"),
    ]
)

logger = logging.getLogger("TelegramBot")
