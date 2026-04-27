"""Entry point: starts the Telegram bot and the APScheduler daily job."""
import asyncio
import logging
import os
import signal

from dotenv import load_dotenv
from telegram.ext import Application

from telegram_bot import build_application
from scheduler import setup_scheduler

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


async def post_init(app: Application) -> None:
    """Called by python-telegram-bot after the bot is initialized, inside its event loop."""
    token = _require_env("TELEGRAM_BOT_TOKEN")
    chat_id = _require_env("TELEGRAM_CHAT_ID")

    scheduler = setup_scheduler(app.bot, chat_id)
    scheduler.start()
    app.bot_data["scheduler"] = scheduler
    logger.info("APScheduler started — daily fetch job scheduled for 08:00 UTC")

    await app.bot.set_my_commands([
        ("start",  "Show help and available commands"),
        ("fetch",  "Fetch today's 4-5 newest AI papers"),
        ("more",   "Fetch 4-5 more papers (going further back)"),
        ("today",  "List papers already fetched today"),
        ("search", "Search stored papers by keyword"),
    ])


async def post_shutdown(app: Application) -> None:
    scheduler = app.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")


def main() -> None:
    token = _require_env("TELEGRAM_BOT_TOKEN")
    _require_env("TELEGRAM_CHAT_ID")
    _require_env("OPENAI_API_KEY")
    _require_env("SUPABASE_URL")
    _require_env("SUPABASE_KEY")

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    logger.info("Starting AI Papers Agent…")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message"],
    )


if __name__ == "__main__":
    main()
