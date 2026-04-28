/**
 * Supabase Edge Function — daily-fetch
 * Scheduled via supabase/config.toml: "0 2 * * *" (02:00 UTC every day)
 *
 * Pipeline:
 *   1. Pull all stored arxiv_ids from Supabase (dedup)
 *   2. Fetch up to 5 newest papers from ArXiv API
 *   3. For each new paper, call Euri API (GPT-4o) for explanation + score
 *   4. Store ALL papers in Supabase (regardless of score)
 *   5. Advance the /more cursor to the oldest date seen
 *   6. Send papers scoring 7+ to Telegram; log the run
 */

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

// ── Environment ──────────────────────────────────────────────────────────────

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SUPABASE_KEY = Deno.env.get("SUPABASE_KEY")!; // service-role key
const EURI_API_KEY = Deno.env.get("EURI_API_KEY")!;
const TELEGRAM_BOT_TOKEN = Deno.env.get("TELEGRAM_BOT_TOKEN")!;
const TELEGRAM_CHAT_ID = Deno.env.get("TELEGRAM_CHAT_ID")!;

const ARXIV_API = "https://export.arxiv.org/api/query";
const ARXIV_QUERY = "cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR cat:stat.ML";
const EURI_BASE = "https://api.euron.one/api/v1/euri";
const TG_API = `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}`;

const TOPIC_OPTIONS = [
  "LLMs", "agents", "agentic AI", "multi-agent systems", "RAG",
  "fine-tuning", "reasoning models", "benchmarks", "evaluation",
  "training", "inference", "safety", "alignment", "tool use",
  "chain of thought", "RLHF", "instruction tuning",
];

// ── Types ────────────────────────────────────────────────────────────────────

interface Paper {
  arxiv_id: string;
  title: string;
  authors: string;
  abstract: string;
  link: string;
  date_published: string;
}

interface Explanation {
  plain_summary: string;
  key_contributions: string;
  code_example: string;
  topics: string[];
  relevance_score: number | null;
}

type FullPaper = Paper & Explanation;

// ── ArXiv fetch ───────────────────────────────────────────────────────────────

async function fetchArxivPapers(
  storedIds: Set<string>,
  count = 5,
): Promise<Paper[]> {
  const params = new URLSearchParams({
    search_query: ARXIV_QUERY,
    max_results: "30",
    sortBy: "submittedDate",
    sortOrder: "descending",
  });

  const resp = await fetch(`${ARXIV_API}?${params}`);
  if (!resp.ok) throw new Error(`ArXiv API ${resp.status}`);
  const xml = await resp.text();

  const papers: Paper[] = [];

  for (const [, entry] of xml.matchAll(/<entry>([\s\S]*?)<\/entry>/g)) {
    if (papers.length >= count) break;

    // ID: http://arxiv.org/abs/2401.12345v1 — strip version suffix
    const idMatch = entry.match(
      /<id>\s*https?:\/\/arxiv\.org\/abs\/([^v\s<]+)/,
    );
    if (!idMatch) continue;
    const arxiv_id = idMatch[1].trim();
    if (storedIds.has(arxiv_id)) continue;

    const title =
      entry.match(/<title>([\s\S]*?)<\/title>/)?.[1]
        ?.trim()
        .replace(/\s+/g, " ") ?? "";
    const abstract =
      entry.match(/<summary>([\s\S]*?)<\/summary>/)?.[1]
        ?.trim()
        .replace(/\s+/g, " ") ?? "";
    const date_published =
      entry.match(/<published>([\s\S]*?)<\/published>/)?.[1]?.trim() ?? "";
    const authorNames = [...entry.matchAll(/<name>([\s\S]*?)<\/name>/g)].map(
      (m) => m[1].trim(),
    );

    if (!title) continue;

    papers.push({
      arxiv_id,
      title,
      authors: authorNames.join(", "),
      abstract,
      link: `https://arxiv.org/abs/${arxiv_id}`,
      date_published,
    });
  }

  return papers;
}

// ── GPT-4o via Euri API ───────────────────────────────────────────────────────

async function explainPaper(paper: Paper): Promise<Explanation> {
  const prompt =
    `Analyze this AI research paper and return a JSON object with exactly these five keys:\n\n` +
    `Paper Title: ${paper.title}\n` +
    `Authors: ${paper.authors || "Not specified"}\n` +
    `Abstract: ${paper.abstract.slice(0, 3000)}\n\n` +
    `JSON keys to return:\n` +
    `1. "explanation" — 3 to 4 paragraphs of plain English explaining what the paper does, ` +
    `why the problem matters, how their approach works, and what the results show.\n` +
    `2. "contributions" — a single string with 4-6 bullet points (each starting with "• ") ` +
    `listing the specific technical contributions.\n` +
    `3. "example" — 15-25 lines of Python pseudo-code or a clearly commented conceptual ` +
    `code snippet that illustrates the paper's core idea. Use comments to explain steps.\n` +
    `4. "topics" — a JSON array of 3-6 strings chosen from: ${JSON.stringify(TOPIC_OPTIONS)}\n` +
    `5. "relevance_score" — an integer 1-10: 10=landmark, 7-9=clearly relevant, ` +
    `4-6=adjacent, 1-3=tangential. Papers scoring 7+ will be sent to subscribers.\n\n` +
    `Return only the JSON object, no extra text.`;

  const resp = await fetch(`${EURI_BASE}/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${EURI_API_KEY}`,
    },
    body: JSON.stringify({
      model: "gpt-4o",
      messages: [
        {
          role: "system",
          content:
            "You are an expert AI researcher who excels at explaining complex research papers. Always return valid JSON.",
        },
        { role: "user", content: prompt },
      ],
      response_format: { type: "json_object" },
      temperature: 0.65,
      max_tokens: 1900,
    }),
  });

  if (!resp.ok) throw new Error(`Euri API ${resp.status}: ${await resp.text()}`);

  const data = await resp.json();
  const content = JSON.parse(data.choices[0].message.content);

  let score: number | null = null;
  if (content.relevance_score != null) {
    const raw = parseInt(String(content.relevance_score));
    if (!isNaN(raw)) score = Math.max(1, Math.min(10, raw));
  }

  const coerceTopics = (raw: unknown): string[] => {
    if (Array.isArray(raw)) return raw.map(String).filter(Boolean);
    if (typeof raw === "string") return raw.split(",").map((t) => t.trim()).filter(Boolean);
    return [];
  };

  return {
    plain_summary: String(content.explanation ?? "").trim(),
    key_contributions: String(content.contributions ?? "").trim(),
    code_example: String(content.example ?? "").trim(),
    topics: coerceTopics(content.topics),
    relevance_score: score,
  };
}

// ── MarkdownV2 helpers ────────────────────────────────────────────────────────

// Body text — escape all 18 reserved chars
function esc(text: string): string {
  return text.replace(/([_*[\]()~`>#+\-=|{}.!\\])/g, "\\$1");
}

// URL context — only \ and ) need escaping
function escUrl(url: string): string {
  return url.replace(/[\\)]/g, (c) => "\\" + c);
}

// Code-block interior — only \ and ` need escaping
function escCode(text: string): string {
  return text.replace(/[\\`]/g, (c) => "\\" + c);
}

// ── Telegram helpers ──────────────────────────────────────────────────────────

async function tgSend(text: string): Promise<void> {
  const resp = await fetch(`${TG_API}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: TELEGRAM_CHAT_ID,
      text,
      parse_mode: "MarkdownV2",
      disable_web_page_preview: true,
    }),
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`Telegram ${resp.status}: ${body}`);
  }
}

function formatPaper(p: FullPaper): string {
  const score = p.relevance_score;
  const scoreStr = score != null ? `⭐ *Relevance:* ${esc(String(score))}/10\n` : "";
  const topicStr = p.topics.length
    ? `🏷 ${esc(p.topics.join(" · "))}\n`
    : "";

  return (
    `🧠 *${esc(p.title)}*\n\n` +
    `👥 ${esc(p.authors.slice(0, 120))}\n` +
    `📅 ${esc(p.date_published.slice(0, 10))}\n` +
    `🔗 [arxiv\\.org/abs/${esc(p.arxiv_id)}](${escUrl(p.link)})\n\n` +
    `📖 *Summary*\n${esc(p.plain_summary.slice(0, 800))}\n\n` +
    `🎯 *Key Contributions*\n${esc(p.key_contributions)}\n\n` +
    "```python\n" +
    escCode(p.code_example.slice(0, 800)) +
    "\n```\n\n" +
    topicStr +
    scoreStr +
    `_Powered by AI Papers Agent_`
  );
}

// ── Main handler ──────────────────────────────────────────────────────────────

Deno.serve(async (_req) => {
  const supabase = createClient(SUPABASE_URL, SUPABASE_KEY);

  try {
    // 1. Collect stored IDs for dedup
    const { data: storedRows, error: idErr } = await supabase
      .from("papers")
      .select("arxiv_id");
    if (idErr) throw new Error(`Supabase select: ${idErr.message}`);
    const storedIds = new Set<string>(
      (storedRows ?? []).map((r: { arxiv_id: string }) => r.arxiv_id),
    );

    // 2. Fetch new papers from ArXiv
    const papers = await fetchArxivPapers(storedIds);

    if (papers.length === 0) {
      await tgSend(
        "📭 Daily fetch: no new papers found\\. Try /fetch manually later\\.",
      );
      return new Response(JSON.stringify({ evaluated: 0, sent: 0 }), {
        status: 200,
      });
    }

    // 3. Explain + store each paper
    const highScoring: FullPaper[] = [];
    let oldestDate: Date | null = null;

    for (const paper of papers) {
      let expl: Explanation;
      try {
        expl = await explainPaper(paper);
      } catch (e) {
        console.error(`explain failed for ${paper.arxiv_id}:`, e);
        expl = {
          plain_summary: paper.abstract.slice(0, 500) + "...",
          key_contributions: "• Could not generate contributions at this time.",
          code_example: "# Could not generate example at this time.",
          topics: [],
          relevance_score: null,
        };
      }

      await supabase.from("papers").insert({
        arxiv_id: paper.arxiv_id,
        title: paper.title,
        authors: paper.authors,
        abstract: paper.abstract,
        link: paper.link,
        date_published: paper.date_published || null,
        date_fetched: new Date().toISOString(),
        plain_summary: expl.plain_summary,
        key_contributions: expl.key_contributions,
        code_example: expl.code_example,
        topics: expl.topics,
        relevance_score: expl.relevance_score,
      });

      if (paper.date_published) {
        const d = new Date(paper.date_published);
        if (!oldestDate || d < oldestDate) oldestDate = d;
      }

      if (expl.relevance_score != null && expl.relevance_score >= 7) {
        highScoring.push({ ...paper, ...expl });
      }
    }

    // 4. Advance /more cursor (only moves backward in time)
    if (oldestDate) {
      const { data: cursorRow } = await supabase
        .from("fetch_state")
        .select("cursor_date")
        .eq("id", 1)
        .single();

      const current = cursorRow?.cursor_date
        ? new Date(cursorRow.cursor_date)
        : null;

      if (!current || oldestDate < current) {
        await supabase.from("fetch_state").upsert({
          id: 1,
          cursor_date: oldestDate.toISOString(),
          updated_at: new Date().toISOString(),
        });
      }
    }

    // 5. Log the run
    await supabase.from("fetch_logs").insert({
      run_date: new Date().toISOString(),
      papers_fetched: highScoring.length,
      triggered_by: "scheduler",
    });

    // 6. Send to Telegram
    if (highScoring.length === 0) {
      await tgSend(
        `📬 *Daily Fetch* — ${esc(String(papers.length))} paper(s) evaluated, none scored 7\\+\\.\n` +
          `_All stored in archive\\._`,
      );
      return new Response(
        JSON.stringify({ evaluated: papers.length, sent: 0 }),
        { status: 200 },
      );
    }

    await tgSend(
      `📬 *Daily AI Papers* — ${esc(String(highScoring.length))} paper(s) ` +
        `\\(from ${esc(String(papers.length))} evaluated\\)\n` +
        `_${esc(new Date().toISOString().slice(0, 10))}_`,
    );

    for (const paper of highScoring) {
      try {
        await tgSend(formatPaper(paper));
        await new Promise((r) => setTimeout(r, 500)); // Telegram rate-limit buffer
      } catch (e) {
        console.error(`send failed for ${paper.arxiv_id}:`, e);
      }
    }

    return new Response(
      JSON.stringify({ evaluated: papers.length, sent: highScoring.length }),
      { status: 200 },
    );
  } catch (err) {
    console.error("daily-fetch edge function failed:", err);
    try {
      await tgSend(
        "❌ Daily fetch \\(Edge Function\\) failed\\. Check Supabase logs\\.",
      );
    } catch { /* ignore secondary failure */ }
    return new Response(JSON.stringify({ error: String(err) }), {
      status: 500,
    });
  }
});
