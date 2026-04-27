import json
import logging
import os
from typing import Dict, List

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_client: OpenAI | None = None

_TOPIC_OPTIONS = [
    "LLMs", "agents", "agentic AI", "multi-agent systems", "RAG",
    "fine-tuning", "reasoning models", "benchmarks", "evaluation",
    "training", "inference", "safety", "alignment", "tool use",
    "chain of thought", "RLHF", "instruction tuning",
]

_SYSTEM_PROMPT = (
    "You are an expert AI researcher who excels at explaining complex research "
    "papers in clear, accessible language. Always return valid JSON."
)

_USER_TEMPLATE = """\
Analyze this AI research paper and return a JSON object with exactly these four keys:

Paper Title: {title}
Authors: {authors}
Abstract: {abstract}

JSON keys to return:
1. "explanation" — 3 to 4 paragraphs of plain English explaining what the paper does,
   why the problem matters, how their approach works, and what the results show.
2. "contributions" — a single string with 4-6 bullet points (each starting with "• ")
   listing the specific technical contributions.
3. "example" — 15-25 lines of Python pseudo-code or a clearly commented conceptual
   code snippet that illustrates the paper's core idea. Use comments to explain steps.
4. "topics" — a JSON array of 3-6 strings chosen from this list (pick the best matches):
   {topics}

Return only the JSON object, no extra text.
"""


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.environ["EURI_API_KEY"],
            base_url="https://api.euron.one/api/v1/euri",
        )
    return _client


def generate_explanation(
    title: str,
    abstract: str,
    authors: str = "",
) -> Dict:
    """Call GPT-4o and return explanation, contributions, example, and topics."""
    prompt = _USER_TEMPLATE.format(
        title=title,
        authors=authors or "Not specified",
        abstract=abstract[:3000],  # guard against extremely long abstracts
        topics=json.dumps(_TOPIC_OPTIONS),
    )

    try:
        response = _get_client().chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.65,
            max_tokens=1800,
        )
        data = json.loads(response.choices[0].message.content)
    except Exception as exc:
        logger.error("OpenAI call failed for '%s': %s", title[:60], exc)
        return {
            "summary": abstract[:500] + "...",
            "contributions": "• Could not generate contributions at this time.",
            "example": "# Could not generate example at this time.",
            "topics": [],
        }

    return {
        "summary": data.get("explanation", "").strip(),
        "contributions": data.get("contributions", "").strip(),
        "example": data.get("example", "").strip(),
        "topics": _coerce_topics(data.get("topics", [])),
    }


def _coerce_topics(raw) -> List[str]:
    """Accept list or comma-string from the model."""
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if t]
    if isinstance(raw, str):
        return [t.strip() for t in raw.split(",") if t.strip()]
    return []
