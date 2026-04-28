import logging

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

from database import get_weekly_top_papers
from telegram_bot import send_long_message, format_weekly_digest

logger = logging.getLogger(__name__)

# Daily paper fetching is handled by the Supabase Edge Function at 02:00 UTC.
# This scheduler owns only the weekly digest (Sunday 09:00 UTC).


async def weekly_digest_job(bot: Bot, chat_id: str) -> None:
    """09:00 UTC every Sunday — send the top 5 papers of the past week by score."""
    logger.info("Weekly digest job started")
    try:
        papers = get_weekly_top_papers(n=5, days=7)
        await send_long_message(bot, chat_id, format_weekly_digest(papers))
        logger.info("Weekly digest sent — %d paper(s)", len(papers))
    except Exception:
        logger.exception("Weekly digest job failed")
        try:
            await bot.send_message(
                chat_id=chat_id,
                text="❌ Weekly digest failed\\. Check logs\\.",
                parse_mode="MarkdownV2",
            )
        except Exception:
            pass


def setup_scheduler(bot: Bot, chat_id: str) -> AsyncIOScheduler:
    """Return a configured AsyncIOScheduler with the weekly digest job."""
    scheduler = AsyncIOScheduler(timezone=pytz.utc)

    # Weekly digest — every Sunday at 09:00 UTC
    scheduler.add_job(
        weekly_digest_job,
        trigger="cron",
        day_of_week="sun",
        hour=9,
        minute=0,
        args=[bot, chat_id],
        id="weekly_digest",
        name="Weekly AI Papers Digest",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    return scheduler
