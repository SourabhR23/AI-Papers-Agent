"""
Telegram command poller — run by GitHub Actions every 5 minutes.

Flow:
  1. Read last processed update_id (offset) from Supabase
  2. Call Telegram getUpdates with that offset
  3. Advance the offset immediately so every message is seen exactly once
  4. Filter to commands from the authorised chat sent within MAX_AGE_SECONDS
  5. Execute each command in order; send errors back to Telegram
"""
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# 2 hours: GitHub Actions free tier can delay cron jobs by 20–60+ minutes.
# Commands older than this are marked seen but not executed.
MAX_AGE_SECONDS = 2 * 60 * 60


# ── Utilities ─────────────────────────────────────────────────────────────────

def _require(key: str) -> str:
    v = os.environ.get(key)
    if not v:
        sys.exit(f"ERROR: missing required environment variable: {key}")
    return v


def _esc(text: str) -> str:
    """MarkdownV2 body-text escape."""
    s = str(text or "").replace("\\", "\\\\")
    for ch in "_*[]()~`>#+=|{}.!-":
        s = s.replace(ch, f"\\{ch}")
    return s


# ── Command handlers ──────────────────────────────────────────────────────────

async def _fetch(bot, chat_id: str) -> None:
    from database import get_all_stored_ids, log_fetch_run
    from fetcher import fetch_latest
    from telegram_bot import process_and_send_papers

    skip_ids = set(get_all_stored_ids())
    papers = fetch_latest(count=5, skip_ids=skip_ids)

    if not papers:
        await bot.send_message(
            chat_id=chat_id,
            text="📭 No new papers found\\. All recent papers are already in the archive\\.",
            parse_mode="MarkdownV2",
        )
        return

    sent = await process_and_send_papers(papers, bot, chat_id, triggered_by="command")
    log_fetch_run(sent, "command")
    logger.info("/fetch — %d paper(s) sent", sent)


async def _more(bot, chat_id: str) -> None:
    from database import get_all_stored_ids, get_cursor_date, log_fetch_run
    from fetcher import fetch_before
    from telegram_bot import process_and_send_papers

    cursor = get_cursor_date()
    if cursor is None:
        await bot.send_message(
            chat_id=chat_id,
            text="ℹ️ No cursor found — run /fetch first to establish a starting point\\.",
            parse_mode="MarkdownV2",
        )
        return

    skip_ids = set(get_all_stored_ids())
    papers = fetch_before(before_date=cursor, count=5, skip_ids=skip_ids)

    if not papers:
        await bot.send_message(
            chat_id=chat_id,
            text="📭 No more unseen papers before the current cursor\\.",
            parse_mode="MarkdownV2",
        )
        return

    sent = await process_and_send_papers(papers, bot, chat_id, triggered_by="command")
    log_fetch_run(sent, "command")
    logger.info("/more — %d paper(s) sent", sent)


async def _today(bot, chat_id: str) -> None:
    from database import get_today_papers
    from telegram_bot import format_today_list, send_long_message

    papers = get_today_papers()
    await send_long_message(bot, chat_id, format_today_list(papers))
    logger.info("/today — %d paper(s) listed", len(papers))


async def _search(bot, chat_id: str, keyword: str) -> None:
    if not keyword.strip():
        await bot.send_message(
            chat_id=chat_id,
            text="Usage: /search \\<keyword\\>\nExample: /search chain of thought",
            parse_mode="MarkdownV2",
        )
        return

    from database import search_papers
    from telegram_bot import format_search_results, send_long_message

    papers = search_papers(keyword.strip())
    await send_long_message(bot, chat_id, format_search_results(papers, keyword.strip()))
    logger.info("/search %r — %d result(s)", keyword.strip(), len(papers))


async def _trends(bot, chat_id: str) -> None:
    from database import get_topic_trends
    from telegram_bot import format_trends, send_long_message

    topic_counts, total = get_topic_trends(days=7)
    await send_long_message(bot, chat_id, format_trends(topic_counts, total))
    logger.info("/trends — %d topic(s) returned", len(topic_counts))


async def _ask(bot, chat_id: str, question: str) -> None:
    if not question.strip():
        await bot.send_message(
            chat_id=chat_id,
            text="Usage: /ask \\<question\\>\nExample: /ask What is RAG\\?",
            parse_mode="MarkdownV2",
        )
        return

    await bot.send_message(
        chat_id=chat_id,
        text="🔍 Searching papers and generating answer\\.\\.\\.",
        parse_mode="MarkdownV2",
    )

    from database import search_for_ask
    from explainer import answer_question
    from telegram_bot import format_ask_response, send_long_message

    papers = search_for_ask(question.strip())
    if not papers:
        await bot.send_message(
            chat_id=chat_id,
            text="📭 No relevant papers found\\. Run /fetch first to build the archive\\.",
            parse_mode="MarkdownV2",
        )
        return

    answer = answer_question(question.strip(), papers)
    await send_long_message(bot, chat_id, format_ask_response(answer, papers))
    logger.info("/ask complete")


async def _status(bot, chat_id: str) -> None:
    from database import get_status

    data = get_status()
    total = data["total"]
    last  = data["last_run"]

    if last:
        run_dt   = datetime.fromisoformat(last["run_date"].replace("Z", "+00:00"))
        date_str = run_dt.strftime("%d %b %Y at %H:%M UTC")
        last_lines = (
            f"🕐 Last fetch: {_esc(date_str)}\n"
            f"📦 Papers sent: {last['papers_fetched']}\n"
            f"⚙️ Triggered by: {_esc(last['triggered_by'])}"
        )
    else:
        last_lines = "_No fetch runs recorded yet — run /fetch first\\._"

    await bot.send_message(
        chat_id=chat_id,
        text=(
            "📊 *AI Papers Archive Status*\n\n"
            f"📚 Total papers stored: {total}\n"
            f"{last_lines}"
        ),
        parse_mode="MarkdownV2",
    )
    logger.info("/status — %d total papers", total)


async def _help(bot, chat_id: str) -> None:
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "🤖 *AI Papers Agent*\n\n"
            "/fetch — fetch 4\\-5 newest AI papers\n"
            "/more — fetch 4\\-5 older papers \\(cursor moves back each time\\)\n"
            "/today — papers fetched today with titles and links\n"
            "/search \\<keyword\\> — search the stored archive\n"
            "/trends — top trending AI topics from this week's papers\n"
            "/ask \\<question\\> — answer a question from stored papers\n"
            "/status — total papers stored and last fetch info\n"
            "/help — show this message\n\n"
            "_Commands are checked every 5 min via GitHub Actions\\._"
        ),
        parse_mode="MarkdownV2",
    )


# ── Router ────────────────────────────────────────────────────────────────────

_COMMANDS = {
    "/fetch":  lambda bot, cid, args: _fetch(bot, cid),
    "/more":   lambda bot, cid, args: _more(bot, cid),
    "/today":  lambda bot, cid, args: _today(bot, cid),
    "/search": lambda bot, cid, args: _search(bot, cid, args),
    "/trends": lambda bot, cid, args: _trends(bot, cid),
    "/ask":    lambda bot, cid, args: _ask(bot, cid, args),
    "/status": lambda bot, cid, args: _status(bot, cid),
    "/help":   lambda bot, cid, args: _help(bot, cid),
}


async def _dispatch(text: str, bot, chat_id: str) -> None:
    parts  = text.split(None, 1)
    cmd    = parts[0].split("@")[0].lower()   # strip /cmd@botname suffix
    args   = parts[1].strip() if len(parts) > 1 else ""
    handler = _COMMANDS.get(cmd)
    if handler is None:
        logger.info("Ignoring unknown command: %s", cmd)
        return
    logger.info("Executing: %s", cmd)
    await handler(bot, chat_id, args)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    from telegram import Bot
    from database import get_telegram_offset, set_telegram_offset

    token   = _require("TELEGRAM_BOT_TOKEN")
    chat_id = _require("TELEGRAM_CHAT_ID")
    _require("EURI_API_KEY")
    _require("SUPABASE_URL")
    _require("SUPABASE_KEY")

    async with Bot(token=token) as bot:
        offset = get_telegram_offset()
        logger.info("Polling from offset=%d", offset)

        updates = await bot.get_updates(
            offset=offset if offset > 0 else None,
            limit=100,
            timeout=0,
            allowed_updates=["message"],
        )

        if not updates:
            logger.info("No new updates — done")
            return

        # Advance offset first — guarantees every update is seen exactly once
        # even if this run crashes mid-execution.
        new_offset = updates[-1].update_id + 1
        set_telegram_offset(new_offset)
        logger.info("Offset advanced to %d  (%d update(s) fetched)", new_offset, len(updates))

        now    = time.time()
        cutoff = now - MAX_AGE_SECONDS

        commands: list[str] = []
        for update in updates:
            msg = update.message
            if not msg or not msg.text:
                continue
            if str(msg.chat.id) != str(chat_id):
                continue
            age = now - msg.date.timestamp()
            if age > MAX_AGE_SECONDS:
                logger.info("Skipping stale message (%.0fs old): %s", age, msg.text.split()[0])
                continue
            if msg.text.strip().startswith("/"):
                commands.append(msg.text.strip())

        if not commands:
            logger.info("No actionable commands in this batch — done")
            return

        logger.info("%d command(s) to run", len(commands))

        for cmd_text in commands:
            try:
                await _dispatch(cmd_text, bot, chat_id)
            except Exception:
                logger.exception("Command failed: %s", cmd_text.split()[0])
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"❌ *{_esc(cmd_text.split()[0])}* failed\\.\n"
                        "Check the GitHub Actions run log for details\\."
                    ),
                    parse_mode="MarkdownV2",
                )


if __name__ == "__main__":
    asyncio.run(main())
