import logging
import re
from datetime import date, timedelta, timezone, datetime
from typing import List, Dict, Tuple

from telegram import Update, Bot
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from database import (
    get_all_stored_ids, store_paper, get_today_papers, search_papers,
    log_fetch_run, get_cursor_date, update_cursor_date,
    search_for_ask, get_weekly_top_papers, get_topic_trends,
)
from fetcher import fetch_latest, fetch_before
from explainer import generate_explanation, answer_question

logger = logging.getLogger(__name__)

MAX_MSG_LEN = 4096
_SCORE_THRESHOLD = 3 #papers below this score are stored but not sent


# ── MarkdownV2 escape helpers ─────────────────────────────────────────────────

def _mdv2(text: str) -> str:
    text = str(text).replace("\\", "\\\\")
    for ch in "_*[]()~`>#+=|{}.!-":
        text = text.replace(ch, f"\\{ch}")
    return text


def _mdv2_url(url: str) -> str:
    return str(url).replace("\\", "\\\\").replace(")", "\\)")


def _esc_code(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace("`", "\\`")


def _fmt_date(dt) -> str:
    if hasattr(dt, "strftime"):
        return dt.strftime("%d %b %Y")
    return str(dt)


def _first_sentence(text: str, max_chars: int = 160) -> str:
    """Extract the first sentence from a paragraph for digest one-liners."""
    if not text:
        return ""
    m = re.search(r"\.\s", text)
    sentence = text[: m.start() + 1] if m else text
    if len(sentence) > max_chars:
        sentence = sentence[:max_chars] + "…"
    return sentence


def _parse_contributions(raw: str) -> List[str]:
    items = []
    for line in raw.splitlines():
        clean = line.strip().lstrip("•-*▸►▶").strip()
        clean = re.sub(r"^\d+[\.\)]\s*", "", clean)
        if clean:
            items.append(clean)
    return items


# ── Message formatters ────────────────────────────────────────────────────────

def format_paper_message(paper: Dict) -> str:
    title    = _mdv2(paper.get("title", ""))
    authors  = _mdv2(paper.get("authors", ""))
    pub_date = _mdv2(_fmt_date(paper.get("date_published", "")))
    link     = _mdv2_url(paper.get("link", ""))
    today    = _mdv2(date.today().strftime("%d %b %Y"))
    summary  = _mdv2(paper.get("plain_summary", "").strip())

    score = paper.get("relevance_score")
    score_line = f"⭐ Relevance: {score}/10\n" if score is not None else ""

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
        f"{score_line}"
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


def format_digest_header(
    papers: List[Dict],
    triggered_by: str = "command",
    total_evaluated: int = 0,
) -> str:
    fetch_date = _mdv2(date.today().strftime("%d %b %Y"))
    count  = len(papers)
    plural = "s" if count != 1 else ""

    seen: set = set()
    topics: List[str] = []
    for p in papers:
        for t in (p.get("topics") or []):
            if t not in seen:
                topics.append(t)
                seen.add(t)
    topics_str = _mdv2(", ".join(topics[:8]) or "AI Research")

    if total_evaluated > count:
        count_line = (
            f"📦 {count} paper{plural} passing relevance threshold "
            f"\\(from {total_evaluated} evaluated\\)\n"
        )
    else:
        count_line = f"📦 {count} new paper{plural} incoming\n"

    source = "Scheduled daily run" if triggered_by == "scheduler" else "Manual fetch"

    return (
        f"📚 *AI Papers Digest*\n\n"
        f"📅 {fetch_date}\n"
        f"{count_line}"
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
        pub    = _mdv2(_fmt_date(p.get("date_published", "")))
        link   = _mdv2_url(p.get("link", ""))
        topics = _mdv2(", ".join(p.get("topics") or []) or "—")
        title  = _mdv2(p.get("title", ""))
        score  = p.get("relevance_score")
        score_tag = f" ⭐{score}" if score is not None else ""
        lines.append(
            f"{i}\\. *{title}*{_mdv2(score_tag)}\n"
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
        pub     = _mdv2(_fmt_date(p.get("date_published", "")))
        link    = _mdv2_url(p.get("link", ""))
        title   = _mdv2(p.get("title", ""))
        raw     = (p.get("plain_summary") or "")[:200].replace("\n", " ")
        if len(p.get("plain_summary") or "") > 200:
            raw += "…"
        snippet = _mdv2(raw)
        lines.append(
            f"{i}\\. *{title}*\n"
            f"   📅 {pub}  •  [ArXiv ↗]({link})\n"
            f"   {snippet}\n"
        )
    return "\n".join(lines)


def format_weekly_digest(papers: List[Dict]) -> str:
    now = date.today()
    week_start = _mdv2((now - timedelta(days=6)).strftime("%d %b"))
    week_end   = _mdv2(now.strftime("%d %b %Y"))

    if not papers:
        return (
            f"📊 *Weekly AI Papers Digest*\n"
            f"Week of {week_start} — {week_end}\n\n"
            f"No papers found for this week\\. Run /fetch to get started\\."
        )

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    lines  = [
        f"📊 *Weekly AI Papers Digest*",
        f"Week of {week_start} — {week_end}",
        f"",
        f"Top {len(papers)} paper{'s' if len(papers) != 1 else ''} by relevance score:\n",
    ]

    for i, p in enumerate(papers):
        medal   = medals[i] if i < len(medals) else f"{i+1}\\."
        title   = _mdv2(p.get("title", "Unknown"))
        link    = _mdv2_url(p.get("link", ""))
        score   = p.get("relevance_score")
        score_s = f" \\| Score: {score}/10" if score is not None else ""
        oneliner = _mdv2(_first_sentence(p.get("plain_summary") or ""))

        lines.append(
            f"{medal} *{title}*{score_s}\n"
            f"_{oneliner}_\n"
            f"[ArXiv ↗]({link})\n"
        )

    return "\n".join(lines)


def format_trends(
    topic_counts: List[Tuple[str, int]],
    total_papers: int,
    days: int = 7,
) -> str:
    now = date.today()
    week_start = _mdv2((now - timedelta(days=days - 1)).strftime("%d %b"))
    week_end   = _mdv2(now.strftime("%d %b %Y"))

    if not topic_counts:
        return (
            f"📈 *Trending AI Topics*\n"
            f"{week_start} — {week_end}\n\n"
            f"No topic data yet\\. Run /fetch to populate the archive\\."
        )

    top5  = topic_counts[:5]
    lines = [
        f"📈 *Trending AI Topics This Week*",
        f"📅 {week_start} — {week_end}  •  {total_papers} paper{'s' if total_papers != 1 else ''} analyzed\n",
    ]
    icons = ["🔥", "🔥", "📌", "📌", "📌"]
    for i, (topic, count) in enumerate(top5):
        icon = icons[i] if i < len(icons) else "•"
        paper_word = "paper" if count == 1 else "papers"
        lines.append(
            f"{i + 1}\\. {icon} {_mdv2(topic)} — {count} {paper_word}"
        )

    return "\n".join(lines)


def format_ask_response(answer: str, papers: List[Dict]) -> str:
    cited = papers[:5]
    paper_links = "\n".join(
        f"• [{_mdv2(p.get('title', 'Unknown')[:65])}{'…' if len(p.get('title','')) > 65 else ''}]"
        f"({_mdv2_url(p.get('link', ''))})"
        for p in cited
    )
    return (
        f"💬 *Answer*\n\n"
        f"{_mdv2(answer)}\n\n"
        f"📚 *Papers searched:*\n"
        f"{paper_links}"
    )


# ── Send helpers ──────────────────────────────────────────────────────────────

async def send_long_message(bot: Bot, chat_id: str, text: str) -> None:
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


# ── Paper pipeline ────────────────────────────────────────────────────────────

def _advance_cursor(papers: List[Dict]) -> None:
    dates = [p["date_published"] for p in papers if p.get("date_published")]
    if dates:
        update_cursor_date(min(dates))


async def process_and_send_papers(
    papers: List[Dict],
    bot: Bot,
    chat_id: str,
    triggered_by: str = "command",
) -> int:
    """
    For each paper: generate explanation+score, store in DB (all papers).
    Advance the cursor, then send only papers scoring >= SCORE_THRESHOLD.
    Returns count of papers actually sent to Telegram.
    """
    # Phase 1: explain + score + store all
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

    # Advance cursor regardless of score filter
    _advance_cursor(processed)

    # Phase 2: filter by relevance score
    to_send = [p for p in processed if (p.get("relevance_score") or 0) >= _SCORE_THRESHOLD]
    low_count = len(processed) - len(to_send)

    if low_count:
        logger.info(
            "%d paper(s) stored but not sent (relevance_score < %d)",
            low_count, _SCORE_THRESHOLD,
        )

    if not to_send:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"📦 Stored {len(processed)} paper\\(s\\) but none scored "
                f"{_SCORE_THRESHOLD}\\+ for relevance to LLMs/agents/RAG/reasoning\\.\n"
                "Try /more to look at older papers\\."
            ),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return 0

    # Phase 3: digest header + individual messages
    await send_long_message(
        bot, chat_id,
        format_digest_header(to_send, triggered_by, total_evaluated=len(processed)),
    )
    for paper in to_send:
        await send_long_message(bot, chat_id, format_paper_message(paper))

    return len(to_send)


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_fetch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        log_fetch_run(sent, "command")
        if sent:
            await update.message.reply_text(
                f"✅ Sent {sent} paper\\(s\\)\\.", parse_mode=ParseMode.MARKDOWN_V2
            )
    except Exception as exc:
        logger.exception("Error in /fetch")
        await update.message.reply_text(
            f"❌ Error: {_mdv2(str(exc))}", parse_mode=ParseMode.MARKDOWN_V2
        )


async def cmd_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text("⏳ Going further back in time for more papers…")

    try:
        cursor   = get_cursor_date()
        skip_ids = set(get_all_stored_ids())

        if cursor is None:
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
        log_fetch_run(sent, "command")
        if sent:
            await update.message.reply_text(
                f"✅ Sent {sent} older paper\\(s\\)\\.", parse_mode=ParseMode.MARKDOWN_V2
            )
    except Exception as exc:
        logger.exception("Error in /more")
        await update.message.reply_text(
            f"❌ Error: {_mdv2(str(exc))}", parse_mode=ParseMode.MARKDOWN_V2
        )


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ask <question> — answer a question using stored paper summaries."""
    question = " ".join(context.args).strip() if context.args else ""
    if not question:
        await update.message.reply_text(
            "Usage: /ask \\<question\\>\n"
            "Example: /ask What is the difference between RAG and fine\\-tuning\\?",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    await update.message.reply_text("🔍 Searching papers and generating answer…")

    try:
        papers = search_for_ask(question)
        if not papers:
            await update.message.reply_text(
                "📭 No relevant papers found in the database\\.\n"
                "Run /fetch first to build up the archive\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        ans = answer_question(question, papers)
        await send_long_message(
            context.bot,
            str(update.effective_chat.id),
            format_ask_response(ans, papers),
        )
    except Exception as exc:
        logger.exception("Error in /ask")
        await update.message.reply_text(
            f"❌ Error: {_mdv2(str(exc))}", parse_mode=ParseMode.MARKDOWN_V2
        )


async def cmd_trends(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/trends — show the top 5 trending AI topics from this week's papers."""
    try:
        topic_counts, total = get_topic_trends(days=7)
        await update.message.reply_text(
            format_trends(topic_counts, total),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except Exception as exc:
        logger.exception("Error in /trends")
        await update.message.reply_text(
            f"❌ Error: {_mdv2(str(exc))}", parse_mode=ParseMode.MARKDOWN_V2
        )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 *AI Papers Agent*\n\n"
        "Daily commands:\n"
        "/fetch — newest 4\\-5 papers \\(scores 7\\+/10 only\\)\n"
        "/more — go further back in time\n"
        "/today — papers fetched today\n"
        "/search \\<topic\\> — search the archive\n\n"
        "Smart commands:\n"
        "/ask \\<question\\> — ask anything about stored papers\n"
        "/trends — top 5 AI topics trending this week\n\n"
        "_Auto\\-fetched daily at 08:00 UTC • Weekly digest every Sunday_",
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
    app.add_handler(CommandHandler("ask",    cmd_ask))
    app.add_handler(CommandHandler("trends", cmd_trends))
    return app
