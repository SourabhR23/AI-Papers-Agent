import logging

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

from database import get_all_stored_ids, log_fetch_run, get_weekly_top_papers
from fetcher import fetch_latest
from telegram_bot import (
    process_and_send_papers,
    send_long_message,
    format_weekly_digest,
)

logger = logging.getLogger(__name__)


async def daily_fetch_job(bot: Bot, chat_id: str) -> None:
    """02:00 UTC — fetch 5 new papers, score, store, broadcast high-scoring ones."""
    logger.info("Daily fetch job started")
    try:
        skip_ids = set(get_all_stored_ids())
        papers   = fetch_latest(count=5, skip_ids=skip_ids)

        if not papers:
            await bot.send_message(
                chat_id=chat_id,
                text="📭 Daily fetch: no new papers found\\. Try /fetch manually later\\.",
                parse_mode="MarkdownV2",
            )
            return

        sent = await process_and_send_papers(papers, bot, chat_id, triggered_by="scheduler")
        log_fetch_run(sent, "scheduler")
        logger.info("Daily fetch completed — %d paper(s) sent", sent)

    except Exception:
        logger.exception("Daily fetch job failed")
        try:
            await bot.send_message(
                chat_id=chat_id,
                text="❌ Daily fetch failed\\. Check logs\\.",
                parse_mode="MarkdownV2",
            )
        except Exception:
            pass


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
    """Return a configured AsyncIOScheduler with all recurring jobs."""
    scheduler = AsyncIOScheduler(timezone=pytz.utc)

    # Daily paper fetch — every day at 02:00 UTC
    scheduler.add_job(
        daily_fetch_job,
        trigger="cron",
        hour=2,
        minute=0,
        args=[bot, chat_id],
        id="daily_fetch",
        name="Daily AI Papers Fetch",
        replace_existing=True,
        misfire_grace_time=3600,
    )

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
