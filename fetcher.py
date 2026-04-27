import re
import logging
from typing import List, Dict, Optional

import arxiv

logger = logging.getLogger(__name__)

# Broad query covering all requested topics across the main AI/ML ArXiv categories.
# The OR structure ensures we catch papers that may not use the exact category tag.
_QUERY = (
    "(large language model OR LLM OR language model OR "
    "agent OR agentic OR multi-agent OR multiagent OR "
    "retrieval augmented generation OR RAG OR "
    "fine-tuning OR finetuning OR instruction tuning OR "
    "reasoning model OR chain of thought OR "
    "reinforcement learning from human feedback OR RLHF) "
    "AND (cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR cat:cs.MA)"
)


def _normalize_id(entry_id: str) -> str:
    """Strip version suffix from an ArXiv entry ID URL."""
    short = entry_id.rstrip("/").split("/")[-1]
    return re.sub(r"v\d+$", "", short)


def fetch_papers(
    count: int = 5,
    skip_ids: Optional[List[str]] = None,
    max_pool: int = 200,
) -> List[Dict]:
    """Return up to `count` recent ArXiv papers not in `skip_ids`."""
    if skip_ids is None:
        skip_ids = []
    skip_set = set(skip_ids)

    client = arxiv.Client(page_size=50, num_retries=3)
    search = arxiv.Search(
        query=_QUERY,
        max_results=max_pool,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    papers: List[Dict] = []
    for result in client.results(search):
        arxiv_id = _normalize_id(result.entry_id)
        if arxiv_id in skip_set:
            continue

        authors = [a.name for a in result.authors[:5]]
        papers.append({
            "arxiv_id":       arxiv_id,
            "title":          result.title.strip(),
            "authors":        ", ".join(authors),
            "abstract":       result.summary.replace("\n", " ").strip(),
            "link":           f"https://arxiv.org/abs/{arxiv_id}",
            "date_published": result.published,
        })

        if len(papers) >= count:
            break

    logger.info("Fetched %d new papers (skipped %d known IDs)", len(papers), len(skip_set))
    return papers
