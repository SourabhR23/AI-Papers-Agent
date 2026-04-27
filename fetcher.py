import re
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

import arxiv

logger = logging.getLogger(__name__)

# ── ArXiv query ───────────────────────────────────────────────────────────────

_BASE_QUERY = (
    "(large language model OR LLM OR language model OR "
    "agent OR agentic OR multi-agent OR multiagent OR "
    "retrieval augmented generation OR RAG OR "
    "fine-tuning OR finetuning OR instruction tuning OR "
    "reasoning model OR chain of thought OR "
    "reinforcement learning from human feedback OR RLHF) "
    "AND (cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR cat:cs.MA)"
)

# ArXiv API date filter — papers exist from ~2020 onward in these categories.
# Format: YYYYMMDDhhmm (12 digits, UTC).
_DATE_FLOOR = "202001010000"


def _client() -> arxiv.Client:
    return arxiv.Client(page_size=100, num_retries=3, delay_seconds=3)


def _normalize_id(entry_id: str) -> str:
    short = entry_id.rstrip("/").split("/")[-1]
    return re.sub(r"v\d+$", "", short)


def _to_dict(result: arxiv.Result) -> Dict:
    arxiv_id = _normalize_id(result.entry_id)
    return {
        "arxiv_id":       arxiv_id,
        "title":          result.title.strip(),
        "authors":        ", ".join(a.name for a in result.authors[:5]),
        "abstract":       result.summary.replace("\n", " ").strip(),
        "link":           f"https://arxiv.org/abs/{arxiv_id}",
        "date_published": result.published,
    }


# ── Public fetch functions ────────────────────────────────────────────────────

def fetch_latest(
    count: int = 5,
    skip_ids: Optional[Set[str]] = None,
) -> List[Dict]:
    """
    Return the newest `count` papers not in `skip_ids`.

    Scans ArXiv newest-first up to 200 results, stopping early once
    `count` new papers are found. Used by /fetch and the daily scheduler.
    """
    if skip_ids is None:
        skip_ids = set()

    search = arxiv.Search(
        query=_BASE_QUERY,
        max_results=200,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    papers: List[Dict] = []
    scanned = 0
    for result in _client().results(search):
        scanned += 1
        arxiv_id = _normalize_id(result.entry_id)
        if arxiv_id not in skip_ids:
            papers.append(_to_dict(result))
            if len(papers) >= count:
                break

    logger.info(
        "fetch_latest: %d new paper(s) found (scanned %d, skip_ids=%d)",
        len(papers), scanned, len(skip_ids),
    )
    return papers


def fetch_before(
    before_date: datetime,
    count: int = 5,
    skip_ids: Optional[Set[str]] = None,
) -> List[Dict]:
    """
    Return the newest `count` papers published BEFORE `before_date` and not in
    `skip_ids`. Uses ArXiv's submittedDate range filter so the API does the
    heavy filtering — no need to scan past the entire recent catalogue.

    The date range query format is: submittedDate:[YYYYMMDDhhmm TO YYYYMMDDhhmm]
    """
    if skip_ids is None:
        skip_ids = set()

    # Normalise to UTC
    if before_date.tzinfo is None:
        before_date = before_date.replace(tzinfo=timezone.utc)
    cutoff = before_date.astimezone(timezone.utc)

    # Subtract 1 minute so the upper bound is exclusive of the cursor instant
    end_dt  = cutoff - timedelta(minutes=1)
    end_str = end_dt.strftime("%Y%m%d%H%M")

    date_query = f"({_BASE_QUERY}) AND submittedDate:[{_DATE_FLOOR} TO {end_str}]"

    search = arxiv.Search(
        query=date_query,
        max_results=200,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    papers: List[Dict] = []
    scanned = 0
    for result in _client().results(search):
        scanned += 1
        arxiv_id = _normalize_id(result.entry_id)
        if arxiv_id not in skip_ids:
            papers.append(_to_dict(result))
            if len(papers) >= count:
                break

    logger.info(
        "fetch_before(%s): %d new paper(s) found (scanned %d)",
        cutoff.strftime("%Y-%m-%d %H:%M UTC"), len(papers), scanned,
    )
    return papers
