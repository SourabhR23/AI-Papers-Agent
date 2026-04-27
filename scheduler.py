import logging

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot

from database import get_all_stored_ids, store_paper, log_fetch_run
from fetcher import fetch_papers
from explainer import generate_explanation
from telegram_bot import format_paper_message, send_long_message

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
                text="📭 Daily fetch: no new papers found right now. Try /fetch manually later.",
            )
            return

        await bot.send_message(
            chat_id=chat_id,
            text=f"🌅 Good morning! Fetching {len(papers)} new AI paper(s) for today…",
        )

        for paper in papers:
            explanation = generate_explanation(
                title=paper["title"],
                abstract=paper["abstract"],
                authors=paper.get("authors", ""),
            )
            paper.update(explanation)
            store_paper(paper)
            await send_long_message(bot, chat_id, format_paper_message(paper))

        log_fetch_run(len(papers), "scheduler")
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ Done! Sent {len(papers)} paper(s). Use /today to see the full list.",
        )
        logger.info("Daily fetch job completed — sent %d papers", len(papers))

    except Exception:
        logger.exception("Daily fetch job failed")
        try:
            await bot.send_message(chat_id=chat_id, text="❌ Daily fetch failed. Check logs.")
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
        misfire_grace_time=3600,  # allow up to 1h late start if the process was down
    )
    return scheduler
