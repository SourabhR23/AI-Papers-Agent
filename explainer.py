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

_EXPLAIN_TEMPLATE = """\
Analyze this AI research paper and return a JSON object with exactly these five keys:

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
5. "relevance_score" — an integer from 1 to 10 rating how directly relevant this paper
   is to the core topics of LLMs, AI agents, reasoning, RAG, or fine-tuning:
     10 = landmark paper that directly advances one of these areas as its primary contribution
     7-9 = clearly and substantially relevant to at least one core topic
     4-6 = touches these topics as context but focuses on something adjacent
     1-3 = only tangentially related; mostly about other ML/AI sub-fields
   Papers scoring 7+ will be sent to subscribers; lower scores are archived only.

Return only the JSON object, no extra text.
"""

_ASK_SYSTEM = (
    "You are an AI research assistant with access to a database of paper summaries. "
    "Answer questions accurately and concisely, citing specific paper titles. "
    "If the provided papers don't contain enough information, say so clearly."
)

_ASK_TEMPLATE = """\
Using ONLY the following paper summaries from a research archive, answer the user's question.
Cite specific paper titles when they are directly relevant to your answer.
Be concise: answer in 3-6 sentences.

--- PAPERS ---
{context}
--- END PAPERS ---

Question: {question}
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
    """Call GPT-4o and return explanation, contributions, example, topics, and relevance_score."""
    prompt = _EXPLAIN_TEMPLATE.format(
        title=title,
        authors=authors or "Not specified",
        abstract=abstract[:3000],
        topics=json.dumps(_TOPIC_OPTIONS),
    )

    try:
        response = _get_client().chat.completions.create(
            model="gpt-4.1-nano",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.65,
            max_tokens=1900,
        )
        data = json.loads(response.choices[0].message.content)
    except Exception as exc:
        logger.error("GPT-4o call failed for '%s': %s", title[:60], exc)
        return {
            "plain_summary":     abstract[:500] + "...",
            "key_contributions": "• Could not generate contributions at this time.",
            "code_example":      "# Could not generate example at this time.",
            "topics":            [],
            "relevance_score":   None,
        }

    score_raw = data.get("relevance_score")
    try:
        score = max(1, min(10, int(score_raw))) if score_raw is not None else None
    except (TypeError, ValueError):
        score = None

    return {
        "plain_summary":     data.get("explanation", "").strip(),
        "key_contributions": data.get("contributions", "").strip(),
        "code_example":      data.get("example", "").strip(),
        "topics":            _coerce_topics(data.get("topics", [])),
        "relevance_score":   score,
    }


def answer_question(question: str, papers: List[Dict]) -> str:
    """
    Use GPT-4o to answer a question grounded in stored paper summaries.
    Returns a plain-text answer (not MarkdownV2 escaped — caller must escape).
    """
    if not papers:
        return "No relevant papers found in the database for that question."

    context_parts = []
    for p in papers:
        summary = (p.get("plain_summary") or p.get("abstract") or "")[:700]
        context_parts.append(
            f"Title: {p.get('title', 'Unknown')}\n"
            f"Link: {p.get('link', '')}\n"
            f"Summary: {summary}"
        )
    context = "\n\n".join(context_parts)

    prompt = _ASK_TEMPLATE.format(context=context, question=question)

    try:
        response = _get_client().chat.completions.create(
            model="gpt-4.1-nano",
            messages=[
                {"role": "system", "content": _ASK_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=600,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.error("answer_question failed: %s", exc)
        return "Sorry, I encountered an error while generating an answer."


def _coerce_topics(raw) -> List[str]:
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if t]
    if isinstance(raw, str):
        return [t.strip() for t in raw.split(",") if t.strip()]
    return []
