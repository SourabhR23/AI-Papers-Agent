import html
import logging
from datetime import date
from typing import List, Dict

from telegram import Update, Bot
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from database import get_all_stored_ids, store_paper, get_today_papers, search_papers
from fetcher import fetch_papers
from explainer import generate_explanation

logger = logging.getLogger(__name__)

MAX_MSG_LEN = 4096


# ── Formatting helpers ────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    """Escape text for HTML parse mode."""
    return html.escape(str(text))


def format_paper_message(paper: Dict) -> str:
    """Build the full HTML Telegram message for one paper."""
    pub = paper.get("date_published", "")
    if hasattr(pub, "strftime"):
        pub = pub.strftime("%d %b %Y")

    topics_str = ", ".join(paper.get("topics", [])) or "AI Research"
    authors_str = _esc(paper.get("authors", ""))
    example = _esc(paper.get("example", "")).strip()
    contributions = _esc(paper.get("contributions", "")).strip()
    summary = _esc(paper.get("summary", "")).strip()

    message = (
        f"🔬 <b>AI Research Paper</b>\n\n"
        f"📄 <b>{_esc(paper['title'])}</b>\n"
        f"👥 <i>{authors_str}</i>\n"
        f"📅 {_esc(str(pub))}  •  <a href=\"{_esc(paper['link'])}\">ArXiv ↗</a>\n"
        f"🏷 {_esc(topics_str)}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 <b>What's this about?</b>\n\n"
        f"{summary}\n\n"
        f"🎯 <b>Key Contributions</b>\n\n"
        f"{contributions}\n\n"
        f"💻 <b>Core Idea (Simplified)</b>\n\n"
        f"<pre><code>{example}</code></pre>"
    )
    return message


def format_today_list(papers: List[Dict]) -> str:
    if not papers:
        return "📭 No papers fetched today yet. Use /fetch to get today's papers."

    lines = [f"📰 <b>Papers fetched today ({date.today().strftime('%d %b %Y')}):</b>\n"]
    for i, p in enumerate(papers, 1):
        pub = p.get("date_published", "")
        if hasattr(pub, "strftime"):
            pub = pub.strftime("%d %b %Y")
        topics_str = ", ".join(p.get("topics") or []) or "—"
        lines.append(
            f"{i}. <b>{_esc(p['title'])}</b>\n"
            f"   📅 {_esc(str(pub))}  •  <a href=\"{_esc(p['link'])}\">ArXiv ↗</a>\n"
            f"   🏷 {_esc(topics_str)}\n"
        )
    return "\n".join(lines)


def format_search_results(papers: List[Dict], keyword: str) -> str:
    if not papers:
        return f"🔍 No stored papers found matching <b>{_esc(keyword)}</b>."

    lines = [f"🔍 <b>Results for \"{_esc(keyword)}\"</b> — {len(papers)} paper(s):\n"]
    for i, p in enumerate(papers, 1):
        pub = p.get("date_published", "")
        if hasattr(pub, "strftime"):
            pub = pub.strftime("%d %b %Y")
        snippet = (p.get("summary") or "")[:200].replace("\n", " ")
        if len(p.get("summary", "")) > 200:
            snippet += "…"
        lines.append(
            f"{i}. <b>{_esc(p['title'])}</b>\n"
            f"   📅 {_esc(str(pub))}  •  <a href=\"{_esc(p['link'])}\">ArXiv ↗</a>\n"
            f"   {_esc(snippet)}\n"
        )
    return "\n".join(lines)


# ── Telegram send helpers ─────────────────────────────────────────────────────

async def send_long_message(bot: Bot, chat_id: str, text: str) -> None:
    """Split and send a message that may exceed Telegram's 4096-char limit."""
    if len(text) <= MAX_MSG_LEN:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML,
                               disable_web_page_preview=True)
        return

    # Split at double-newline boundaries to preserve paragraph structure
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
        await bot.send_message(chat_id=chat_id, text=chunk, parse_mode=ParseMode.HTML,
                               disable_web_page_preview=True)


async def _process_and_send_papers(papers: List[Dict], bot: Bot, chat_id: str) -> int:
    """Generate explanations, store, and send each paper. Returns count sent."""
    sent = 0
    for paper in papers:
        explanation = generate_explanation(
            title=paper["title"],
            abstract=paper["abstract"],
            authors=paper.get("authors", ""),
        )
        paper.update(explanation)
        store_paper(paper)
        await send_long_message(bot, chat_id, format_paper_message(paper))
        sent += 1
    return sent


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_fetch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/fetch — grab today's 4-5 newest papers, skip already stored ones."""
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text("⏳ Fetching latest AI papers…")

    try:
        stored_ids = get_all_stored_ids()
        papers = fetch_papers(count=5, skip_ids=stored_ids)
        if not papers:
            await update.message.reply_text(
                "✅ All recent papers have already been sent. Try /more for older ones."
            )
            return
        sent = await _process_and_send_papers(papers, context.bot, chat_id)
        await update.message.reply_text(f"✅ Sent {sent} new paper(s).")
    except Exception as exc:
        logger.exception("Error in /fetch")
        await update.message.reply_text(f"❌ Error during fetch: {html.escape(str(exc))}")


async def cmd_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/more — fetch 4-5 more papers going further back, skipping all stored ones."""
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text("⏳ Fetching more AI papers (going further back)…")

    try:
        stored_ids = get_all_stored_ids()
        # Use a larger pool so we can skip many already-stored papers
        papers = fetch_papers(count=5, skip_ids=stored_ids, max_pool=400)
        if not papers:
            await update.message.reply_text(
                "📭 No more unseen papers found in the current search window."
            )
            return
        sent = await _process_and_send_papers(papers, context.bot, chat_id)
        await update.message.reply_text(f"✅ Sent {sent} additional paper(s).")
    except Exception as exc:
        logger.exception("Error in /more")
        await update.message.reply_text(f"❌ Error: {html.escape(str(exc))}")


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/today — list papers already fetched today."""
    try:
        papers = get_today_papers()
        await update.message.reply_text(
            format_today_list(papers),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as exc:
        logger.exception("Error in /today")
        await update.message.reply_text(f"❌ Error: {html.escape(str(exc))}")


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/search <topic> — search stored papers by keyword."""
    keyword = " ".join(context.args).strip() if context.args else ""
    if not keyword:
        await update.message.reply_text("Usage: /search <topic>\nExample: /search RAG")
        return

    try:
        papers = search_papers(keyword)
        await update.message.reply_text(
            format_search_results(papers, keyword),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as exc:
        logger.exception("Error in /search")
        await update.message.reply_text(f"❌ Error: {html.escape(str(exc))}")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 <b>AI Papers Agent</b>\n\n"
        "Commands:\n"
        "/fetch — get today's 4-5 newest papers\n"
        "/more — fetch 4-5 more (going further back)\n"
        "/today — list what was fetched today\n"
        "/search &lt;topic&gt; — search stored papers\n\n"
        "Papers are also auto-fetched daily at 08:00 UTC.",
        parse_mode=ParseMode.HTML,
    )


# ── Application builder ───────────────────────────────────────────────────────

def build_application(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("fetch", cmd_fetch))
    app.add_handler(CommandHandler("more", cmd_more))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("search", cmd_search))
    return app
