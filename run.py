"""
Entry point for GitHub Actions.

    python run.py --action fetch               # fetch & send latest papers
    python run.py --action more                # fetch older papers (cursor)
    python run.py --action today               # list papers fetched today
    python run.py --action search --query rag  # search stored archive
"""
import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _require(key: str) -> str:
    v = os.environ.get(key)
    if not v:
        sys.exit(f"ERROR: missing required environment variable: {key}")
    return v


async def run(action: str, query: str) -> None:
    from telegram import Bot
    from database import (
        get_all_stored_ids,
        get_cursor_date,
        get_today_papers,
        log_fetch_run,
        search_papers,
    )
    from fetcher import fetch_latest, fetch_before
    from telegram_bot import (
        format_search_results,
        format_today_list,
        process_and_send_papers,
        send_long_message,
    )

    token   = _require("TELEGRAM_BOT_TOKEN")
    chat_id = _require("TELEGRAM_CHAT_ID")

    async with Bot(token=token) as bot:

        # ── fetch ─────────────────────────────────────────────────────────────
        if action == "fetch":
            logger.info("Running: fetch")
            skip_ids = set(get_all_stored_ids())
            papers   = fetch_latest(count=5, skip_ids=skip_ids)

            if not papers:
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "📭 No new papers found\\. "
                        "All recent papers are already in the archive\\."
                    ),
                    parse_mode="MarkdownV2",
                )
                return

            sent = await process_and_send_papers(
                papers, bot, chat_id, triggered_by="scheduler"
            )
            log_fetch_run(sent, "scheduler")
            logger.info("fetch done — %d paper(s) sent", sent)

        # ── more ──────────────────────────────────────────────────────────────
        elif action == "more":
            logger.info("Running: more")
            cursor = get_cursor_date()

            if cursor is None:
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "ℹ️ No cursor found\\. "
                        "Run the *fetch* action first to establish a starting point\\."
                    ),
                    parse_mode="MarkdownV2",
                )
                return

            skip_ids = set(get_all_stored_ids())
            papers   = fetch_before(before_date=cursor, count=5, skip_ids=skip_ids)

            if not papers:
                await bot.send_message(
                    chat_id=chat_id,
                    text="📭 No more unseen papers found before the current cursor\\.",
                    parse_mode="MarkdownV2",
                )
                return

            sent = await process_and_send_papers(
                papers, bot, chat_id, triggered_by="command"
            )
            log_fetch_run(sent, "command")
            logger.info("more done — %d paper(s) sent", sent)

        # ── today ─────────────────────────────────────────────────────────────
        elif action == "today":
            logger.info("Running: today")
            papers = get_today_papers()
            await send_long_message(bot, chat_id, format_today_list(papers))
            logger.info("today — %d paper(s) shown", len(papers))

        # ── search ────────────────────────────────────────────────────────────
        elif action == "search":
            if not query.strip():
                sys.exit(
                    "ERROR: --query is required when action=search.\n"
                    "Example: python run.py --action search --query 'chain of thought'"
                )
            logger.info("Running: search — %r", query)
            papers = search_papers(query.strip())
            await send_long_message(
                bot, chat_id, format_search_results(papers, query.strip())
            )
            logger.info("search done — %d result(s)", len(papers))

        else:
            sys.exit(f"Unknown action: {action!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Papers Agent — GitHub Actions runner")
    parser.add_argument(
        "--action",
        choices=["fetch", "more", "today", "search"],
        default="fetch",
    )
    parser.add_argument(
        "--query",
        default="",
        help="Search keyword (required when --action search)",
    )
    args = parser.parse_args()

    _require("EURI_API_KEY")
    _require("SUPABASE_URL")
    _require("SUPABASE_KEY")

    asyncio.run(run(args.action, args.query))


if __name__ == "__main__":
    main()
