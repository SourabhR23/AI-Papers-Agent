import os
import logging
from collections import Counter
from datetime import datetime, date, timedelta, timezone
from typing import List, Dict, Optional, Tuple

from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_client: Optional[Client] = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_KEY"]
        _client = create_client(url, key)
    return _client


# ── Core paper operations ─────────────────────────────────────────────────────

def paper_exists(arxiv_id: str) -> bool:
    result = get_client().table("papers").select("arxiv_id").eq("arxiv_id", arxiv_id).execute()
    return len(result.data) > 0


def store_paper(paper: Dict) -> bool:
    pub_date = paper.get("date_published")
    if hasattr(pub_date, "isoformat"):
        pub_date = pub_date.isoformat()

    try:
        get_client().table("papers").insert({
            "arxiv_id":          paper["arxiv_id"],
            "title":             paper["title"],
            "authors":           paper.get("authors", ""),
            "abstract":          paper.get("abstract", ""),
            "link":              paper["link"],
            "date_published":    pub_date,
            "date_fetched":      datetime.now(timezone.utc).isoformat(),
            "plain_summary":     paper.get("plain_summary", ""),
            "key_contributions": paper.get("key_contributions", ""),
            "code_example":      paper.get("code_example", ""),
            "topics":            paper.get("topics", []),
            "relevance_score":   paper.get("relevance_score"),
        }).execute()
        return True
    except Exception as exc:
        logger.error("Failed to store paper %s: %s", paper.get("arxiv_id"), exc)
        return False


def get_all_stored_ids() -> List[str]:
    result = get_client().table("papers").select("arxiv_id").execute()
    return [row["arxiv_id"] for row in result.data]


def get_today_papers() -> List[Dict]:
    today_start = datetime.combine(date.today(), datetime.min.time()).isoformat()
    result = (
        get_client()
        .table("papers")
        .select("*")
        .gte("date_fetched", today_start)
        .order("date_fetched", desc=True)
        .execute()
    )
    return result.data


def search_papers(keyword: str) -> List[Dict]:
    kw = keyword.strip()
    result = (
        get_client()
        .table("papers")
        .select("*")
        .or_(f"title.ilike.%{kw}%,plain_summary.ilike.%{kw}%")
        .order("date_published", desc=True)
        .limit(10)
        .execute()
    )
    return result.data


# ── /ask search ───────────────────────────────────────────────────────────────

def search_for_ask(question: str, limit: int = 8) -> List[Dict]:
    """
    Broad keyword search for the /ask command.
    Extracts up to 3 meaningful words from the question and OR-searches
    title + plain_summary for each, returning the most relevant results.
    """
    _STOPWORDS = {
        "the", "and", "for", "are", "was", "what", "how", "why", "does",
        "did", "can", "about", "with", "that", "this", "have", "has",
        "been", "from", "which", "when", "where", "who", "will", "would",
    }
    words = [
        w.strip("?.,!;:")
        for w in question.lower().split()
        if len(w.strip("?.,!;:")) >= 3 and w.strip("?.,!;:") not in _STOPWORDS
    ][:3]

    if not words:
        words = [question[:40].strip()]

    # Build one OR clause covering all keywords across title and summary
    conditions = ",".join(
        f"title.ilike.%{w}%,plain_summary.ilike.%{w}%"
        for w in words
    )

    result = (
        get_client()
        .table("papers")
        .select("arxiv_id,title,link,plain_summary,topics,date_published,relevance_score")
        .or_(conditions)
        .order("relevance_score", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


# ── Weekly digest ─────────────────────────────────────────────────────────────

def get_weekly_top_papers(n: int = 5, days: int = 7) -> List[Dict]:
    """Return top N papers from the past `days` days, ordered by relevance_score."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    result = (
        get_client()
        .table("papers")
        .select("arxiv_id,title,link,plain_summary,topics,relevance_score,date_published")
        .gte("date_fetched", since)
        .order("relevance_score", desc=True)
        .limit(n)
        .execute()
    )
    return result.data


# ── /trends ───────────────────────────────────────────────────────────────────

def get_topic_trends(days: int = 7) -> Tuple[List[Tuple[str, int]], int]:
    """
    Count topic frequency across papers fetched in the last `days` days.
    Returns ([(topic, count), ...] sorted descending, total_papers).
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    result = (
        get_client()
        .table("papers")
        .select("topics")
        .gte("date_fetched", since)
        .execute()
    )
    counter: Counter = Counter()
    for row in result.data:
        for topic in (row.get("topics") or []):
            if topic:
                counter[topic] += 1
    return counter.most_common(10), len(result.data)


# ── Cursor ────────────────────────────────────────────────────────────────────

def get_cursor_date() -> Optional[datetime]:
    """Return the oldest date_published we have ever stored, or None."""
    try:
        result = (
            get_client()
            .table("fetch_state")
            .select("cursor_date")
            .eq("id", 1)
            .execute()
        )
        if result.data and result.data[0].get("cursor_date"):
            raw = result.data[0]["cursor_date"]
            if isinstance(raw, str):
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return raw
    except Exception as exc:
        logger.error("Failed to get cursor_date: %s", exc)
    return None


def update_cursor_date(dt: datetime) -> None:
    """Move the cursor backward to `dt` only if `dt` is older than the current cursor."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    current = get_cursor_date()
    if current is not None and current <= dt:
        return  # current cursor is already at or before dt

    try:
        get_client().table("fetch_state").upsert({
            "id":          1,
            "cursor_date": dt.isoformat(),
            "updated_at":  datetime.now(timezone.utc).isoformat(),
        }).execute()
        logger.info("Cursor updated to %s", dt.strftime("%Y-%m-%d %H:%M UTC"))
    except Exception as exc:
        logger.error("Failed to update cursor_date: %s", exc)


# ── Telegram offset ───────────────────────────────────────────────────────────

def get_telegram_offset() -> int:
    """Return last processed Telegram update_id + 1, or 0 on first run."""
    try:
        result = (
            get_client()
            .table("fetch_state")
            .select("telegram_offset")
            .eq("id", 1)
            .execute()
        )
        if result.data and result.data[0].get("telegram_offset") is not None:
            return int(result.data[0]["telegram_offset"])
    except Exception as exc:
        logger.error("Failed to get telegram_offset: %s", exc)
    return 0


def set_telegram_offset(offset: int) -> None:
    """Persist the Telegram update offset so the next poll skips processed updates."""
    try:
        get_client().table("fetch_state").upsert({
            "id":               1,
            "telegram_offset":  offset,
            "updated_at":       datetime.now(timezone.utc).isoformat(),
        }).execute()
        logger.info("telegram_offset set to %d", offset)
    except Exception as exc:
        logger.error("Failed to set telegram_offset: %s", exc)


# ── Status ────────────────────────────────────────────────────────────────────

def get_status() -> Dict:
    """Return total stored paper count and the most recent fetch_logs row."""
    total = 0
    try:
        result = (
            get_client()
            .table("papers")
            .select("arxiv_id", count="exact")
            .execute()
        )
        total = result.count or 0
    except Exception as exc:
        logger.error("Failed to count papers: %s", exc)

    last_run = None
    try:
        result = (
            get_client()
            .table("fetch_logs")
            .select("run_date,papers_fetched,triggered_by")
            .order("run_date", desc=True)
            .limit(1)
            .execute()
        )
        last_run = result.data[0] if result.data else None
    except Exception as exc:
        logger.error("Failed to get last fetch run: %s", exc)

    return {"total": total, "last_run": last_run}


# ── Audit log ─────────────────────────────────────────────────────────────────

def log_fetch_run(papers_fetched: int, triggered_by: str) -> None:
    try:
        get_client().table("fetch_logs").insert({
            "run_date":       datetime.now(timezone.utc).isoformat(),
            "papers_fetched": papers_fetched,
            "triggered_by":   triggered_by,
        }).execute()
    except Exception as exc:
        logger.error("Failed to log fetch run: %s", exc)
