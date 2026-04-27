import logging

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

from database import get_all_stored_ids, log_fetch_run
from fetcher import fetch_papers
from telegram_bot import process_and_send_papers

logger = logging.getLogger(__name__)


async def daily_fetch_job(bot: Bot, chat_id: str) -> None:
    """Scheduled job: fetch 5 new papers, explain, store, and broadcast."""
    logger.info("Daily fetch job started")

    try:
        stored_ids = get_all_stored_ids()
        papers = fetch_papers(count=5, skip_ids=stored_ids)

        if not papers:
            await bot.send_message(
                chat_id=chat_id,
                text="📭 Daily fetch: no new papers found right now\\. Try /fetch manually later\\.",
            )
            return

        sent = await process_and_send_papers(papers, bot, chat_id, triggered_by="scheduler")
        log_fetch_run(sent, "scheduler")
        logger.info("Daily fetch job completed — sent %d papers", sent)

    except Exception:
        logger.exception("Daily fetch job failed")
        try:
            await bot.send_message(chat_id=chat_id, text="❌ Daily fetch failed\\. Check logs\\.")
        except Exception:
            pass


def setup_scheduler(bot: Bot, chat_id: str) -> AsyncIOScheduler:
    """Create and return an AsyncIOScheduler with the daily 08:00 UTC job."""
    scheduler = AsyncIOScheduler(timezone=pytz.utc)
    scheduler.add_job(
        daily_fetch_job,
        trigger="cron",
        hour=8,
        minute=0,
        args=[bot, chat_id],
        id="daily_fetch",
        name="Daily AI Papers Fetch",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    return scheduler
