import os
import logging
from datetime import datetime, date, timezone
from typing import List, Dict, Optional

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
    """
    Move the cursor backward to `dt` if `dt` is older than the current cursor.
    The cursor only ever moves to earlier dates — it represents the furthest
    back in time we have fetched.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    current = get_cursor_date()
    if current is not None and current <= dt:
        # Current cursor is already at or before dt — nothing to do.
        return

    try:
        get_client().table("fetch_state").upsert({
            "id":           1,
            "cursor_date":  dt.isoformat(),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        }).execute()
        logger.info("Cursor updated to %s", dt.strftime("%Y-%m-%d %H:%M UTC"))
    except Exception as exc:
        logger.error("Failed to update cursor_date: %s", exc)


def log_fetch_run(papers_fetched: int, triggered_by: str) -> None:
    try:
        get_client().table("fetch_logs").insert({
            "run_date":       datetime.now(timezone.utc).isoformat(),
            "papers_fetched": papers_fetched,
            "triggered_by":   triggered_by,
        }).execute()
    except Exception as exc:
        logger.error("Failed to log fetch run: %s", exc)
