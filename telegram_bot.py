import logging
import re
from datetime import date
from typing import List, Dict

from telegram import Update, Bot
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from database import (
    get_all_stored_ids, store_paper, get_today_papers, search_papers,
    log_fetch_run, get_cursor_date, update_cursor_date,
)
from fetcher import fetch_latest, fetch_before
from explainer import generate_explanation

logger = logging.getLogger(__name__)

MAX_MSG_LEN = 4096


# ── MarkdownV2 escape helpers ─────────────────────────────────────────────────

def _mdv2(text: str) -> str:
    """Escape arbitrary text for MarkdownV2 (outside formatting entities)."""
    text = str(text).replace("\\", "\\\\")
    for ch in "_*[]()~`>#+=|{}.!-":
        text = text.replace(ch, f"\\{ch}")
    return text


def _mdv2_url(url: str) -> str:
    """Escape a URL for the (url) part of a MarkdownV2 inline link."""
    return str(url).replace("\\", "\\\\").replace(")", "\\)")


def _esc_code(text: str) -> str:
    """Escape text inside a MarkdownV2 triple-backtick code block."""
    return str(text).replace("\\", "\\\\").replace("`", "\\`")


def _fmt_date(dt) -> str:
    if hasattr(dt, "strftime"):
        return dt.strftime("%d %b %Y")
    return str(dt)


def _parse_contributions(raw: str) -> List[str]:
    """Normalize GPT-4o bullet string into plain-text lines."""
    items = []
    for line in raw.splitlines():
        # Strip common bullet prefixes
        clean = line.strip().lstrip("•-*▸►▶").strip()
        # Strip leading numbers like "1." or "2)"
        clean = re.sub(r"^\d+[\.\)]\s*", "", clean)
        if clean:
            items.append(clean)
    return items


# ── Message formatters ────────────────────────────────────────────────────────

def format_paper_message(paper: Dict) -> str:
    """Build a single-paper MarkdownV2 message matching the exact spec."""
    title    = _mdv2(paper.get("title", ""))
    authors  = _mdv2(paper.get("authors", ""))
    pub_date = _mdv2(_fmt_date(paper.get("date_published", "")))
    link     = _mdv2_url(paper.get("link", ""))
    today    = _mdv2(date.today().strftime("%d %b %Y"))
    summary  = _mdv2(paper.get("plain_summary", "").strip())

    contrib_items = _parse_contributions(paper.get("key_contributions", ""))
    contribs = (
        "\n".join(f"\\- {_mdv2(c)}" for c in contrib_items)
        if contrib_items
        else "\\- No contributions listed\\."
    )

    code = _esc_code(paper.get("code_example", "").strip())

    return (
        f"🧠 *{title}*\n"
        f"👥 Authors: {authors}\n"
        f"📅 Published: {pub_date}\n"
        f"🔗 [Read Paper]({link})\n\n"
        f"📖 *What It's About*\n"
        f"{summary}\n\n"
        f"🎯 *Key Contributions*\n"
        f"{contribs}\n\n"
        f"💡 *Simple Example*\n"
        f"```python\n{code}\n```\n\n"
        f"\\-\\-\\-\n"
        f"_Fetched by AI Papers Agent • {today}_"
    )


def format_digest_header(papers: List[Dict], triggered_by: str = "command") -> str:
    """Banner sent before the batch of individual paper messages."""
    fetch_date = _mdv2(date.today().strftime("%d %b %Y"))
    count = len(papers)
    plural = "s" if count != 1 else ""

    # Collect unique topics in insertion order
    seen: set = set()
    topics: List[str] = []
    for p in papers:
        for t in (p.get("topics") or []):
            if t not in seen:
                topics.append(t)
                seen.add(t)
    topics_str = _mdv2(", ".join(topics[:8]) or "AI Research")

    source = "Scheduled daily run" if triggered_by == "scheduler" else "Manual fetch"

    return (
        f"📚 *AI Papers Digest*\n\n"
        f"📅 {fetch_date}\n"
        f"📦 {count} new paper{plural} incoming\n"
        f"🏷 Topics: {topics_str}\n"
        f"⚙️ {_mdv2(source)}\n\n"
        f"_Sending individual papers below\\.\\.\\._"
    )


def format_today_list(papers: List[Dict]) -> str:
    if not papers:
        return "📭 No papers fetched today yet\\. Use /fetch to get today's papers\\."

    today_str = _mdv2(date.today().strftime("%d %b %Y"))
    lines = [f"📰 *Papers fetched today \\({today_str}\\):*\n"]
    for i, p in enumerate(papers, 1):
        pub      = _mdv2(_fmt_date(p.get("date_published", "")))
        link     = _mdv2_url(p.get("link", ""))
        topics   = _mdv2(", ".join(p.get("topics") or []) or "—")
        title    = _mdv2(p.get("title", ""))
        lines.append(
            f"{i}\\. *{title}*\n"
            f"   📅 {pub}  •  [ArXiv ↗]({link})\n"
            f"   🏷 {topics}\n"
        )
    return "\n".join(lines)


def format_search_results(papers: List[Dict], keyword: str) -> str:
    kw = _mdv2(keyword)
    if not papers:
        return f"🔍 No stored papers found matching *{kw}*\\."

    lines = [f"🔍 *Results for \"{kw}\"* — {len(papers)} paper\\(s\\):\n"]
    for i, p in enumerate(papers, 1):
        pub   = _mdv2(_fmt_date(p.get("date_published", "")))
        link  = _mdv2_url(p.get("link", ""))
        title = _mdv2(p.get("title", ""))
        raw   = (p.get("plain_summary") or "")[:200].replace("\n", " ")
        if len(p.get("plain_summary") or "") > 200:
            raw += "…"
        snippet = _mdv2(raw)
        lines.append(
            f"{i}\\. *{title}*\n"
            f"   📅 {pub}  •  [ArXiv ↗]({link})\n"
            f"   {snippet}\n"
        )
    return "\n".join(lines)


# ── Send helpers ──────────────────────────────────────────────────────────────

async def send_long_message(bot: Bot, chat_id: str, text: str) -> None:
    """Send a MarkdownV2 message, splitting at paragraph breaks if > 4096 chars."""
    if len(text) <= MAX_MSG_LEN:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
        )
        return

    chunks: List[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        block = paragraph + "\n\n"
        if len(current) + len(block) > MAX_MSG_LEN:
            if current:
                chunks.append(current.rstrip())
            current = block
        else:
            current += block
    if current.strip():
        chunks.append(current.rstrip())

    for chunk in chunks:
        await bot.send_message(
            chat_id=chat_id,
            text=chunk,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
        )


async def process_and_send_papers(
    papers: List[Dict],
    bot: Bot,
    chat_id: str,
    triggered_by: str = "command",
) -> int:
    """Generate explanations, store all papers, send digest header, then each paper."""
    # Phase 1: explain + store everything before sending anything
    processed: List[Dict] = []
    for paper in papers:
        explanation = generate_explanation(
            title=paper["title"],
            abstract=paper["abstract"],
            authors=paper.get("authors", ""),
        )
        paper.update(explanation)
        store_paper(paper)
        processed.append(paper)

    # Phase 2: digest header (topics are available now from all papers)
    await send_long_message(bot, chat_id, format_digest_header(processed, triggered_by))

    # Phase 3: one message per paper
    for paper in processed:
        await send_long_message(bot, chat_id, format_paper_message(paper))

    return len(processed)


# ── Cursor helper ────────────────────────────────────────────────────────────

def _advance_cursor(papers: List[Dict]) -> None:
    """Push the cursor back to the oldest date_published in this batch."""
    dates = [p["date_published"] for p in papers if p.get("date_published")]
    if dates:
        update_cursor_date(min(dates))


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_fetch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/fetch — grab the newest 4-5 papers not already in the database."""
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text("⏳ Fetching latest AI papers…")

    try:
        skip_ids = set(get_all_stored_ids())
        papers   = fetch_latest(count=5, skip_ids=skip_ids)

        if not papers:
            await update.message.reply_text(
                "✅ All recent papers have already been fetched\\.\n"
                "Use /more to go further back in time\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        sent = await process_and_send_papers(papers, context.bot, chat_id, "command")
        _advance_cursor(papers)
        log_fetch_run(sent, "command")
        await update.message.reply_text(
            f"✅ Sent {sent} new paper\\(s\\)\\.", parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as exc:
        logger.exception("Error in /fetch")
        await update.message.reply_text(
            f"❌ Error: {_mdv2(str(exc))}", parse_mode=ParseMode.MARKDOWN_V2
        )


async def cmd_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/more — fetch 4-5 papers older than the current cursor, skipping all stored."""
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text(
        "⏳ Going further back in time for more papers…",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    try:
        cursor   = get_cursor_date()
        skip_ids = set(get_all_stored_ids())

        if cursor is None:
            # No cursor yet — behave like /fetch but inform user to run /fetch first
            await update.message.reply_text(
                "ℹ️ No fetch history found\\. Run /fetch first to establish a starting point\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        papers = fetch_before(cursor, count=5, skip_ids=skip_ids)

        if not papers:
            await update.message.reply_text(
                "📭 No more unseen papers found before the current cursor\\.\n"
                f"Cursor is at: {_mdv2(cursor.strftime('%d %b %Y %H:%M UTC'))}",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        sent = await process_and_send_papers(papers, context.bot, chat_id, "command")
        _advance_cursor(papers)
        log_fetch_run(sent, "command")
        await update.message.reply_text(
            f"✅ Sent {sent} older paper\\(s\\)\\.", parse_mode=ParseMode.MARKDOWN_V2
        )
    except Exception as exc:
        logger.exception("Error in /more")
        await update.message.reply_text(
            f"❌ Error: {_mdv2(str(exc))}", parse_mode=ParseMode.MARKDOWN_V2
        )


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/today — list papers already fetched today."""
    try:
        papers = get_today_papers()
        await update.message.reply_text(
            format_today_list(papers),
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
        )
    except Exception as exc:
        logger.exception("Error in /today")
        await update.message.reply_text(
            f"❌ Error: {_mdv2(str(exc))}", parse_mode=ParseMode.MARKDOWN_V2
        )


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/search <topic> — search stored papers by keyword."""
    keyword = " ".join(context.args).strip() if context.args else ""
    if not keyword:
        await update.message.reply_text(
            "Usage: /search \\<topic\\>\nExample: /search RAG",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    try:
        papers = search_papers(keyword)
        await update.message.reply_text(
            format_search_results(papers, keyword),
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True,
        )
    except Exception as exc:
        logger.exception("Error in /search")
        await update.message.reply_text(
            f"❌ Error: {_mdv2(str(exc))}", parse_mode=ParseMode.MARKDOWN_V2
        )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 *AI Papers Agent*\n\n"
        "Commands:\n"
        "/fetch — get today's 4\\-5 newest papers\n"
        "/more — fetch 4\\-5 more \\(going further back\\)\n"
        "/today — list what was fetched today\n"
        "/search \\<topic\\> — search stored papers\n\n"
        "_Papers are auto\\-fetched daily at 08:00 UTC\\._",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


# ── Application builder ───────────────────────────────────────────────────────

def build_application(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("fetch",  cmd_fetch))
    app.add_handler(CommandHandler("more",   cmd_more))
    app.add_handler(CommandHandler("today",  cmd_today))
    app.add_handler(CommandHandler("search", cmd_search))
    return app
