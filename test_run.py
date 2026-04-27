#!/usr/bin/env python3
"""
test_run.py — Verify every integration before going live.

Usage
-----
  python test_run.py              # full run, sends a real Telegram message
  python test_run.py --skip-send  # skip Telegram sends, still tests auth

Tests (in order)
-----------------
  1. Environment variables present
  2. Supabase connection + all three tables accessible
  3. Euri API (GPT-4o) responds
  4. Telegram bot auth + optional test message
  5. ArXiv paper fetch (1 paper)
  6. End-to-end: fetch → explain → format → send  (no DB write)

Exit code 0 = all passed, 1 = one or more failed.
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

# ── Terminal colours (degrade gracefully on Windows) ──────────────────────────

def _colour(code: str, text: str) -> str:
    if sys.stdout.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text

def _green(t):  return _colour("92", t)
def _red(t):    return _colour("91", t)
def _yellow(t): return _colour("93", t)
def _bold(t):   return _colour("1",  t)

_PASS = _green("PASS")
_FAIL = _red("FAIL")
_SKIP = _yellow("SKIP")

_results: dict[str, bool] = {}


# ── Reporting helpers ─────────────────────────────────────────────────────────

def _section(n: int, title: str) -> None:
    bar = "─" * 58
    print(f"\n{_bold(bar)}")
    print(f"{_bold(f'  {n}. {title}')}")
    print(_bold(bar))


def _ok(label: str, detail: str = "") -> None:
    suffix = f"  ({detail})" if detail else ""
    print(f"  {_PASS}  {label}{suffix}")


def _err(label: str, exc: Exception) -> None:
    print(f"  {_FAIL}  {label}")
    print(f"         {_red(str(exc))}")


def _skip(label: str) -> None:
    print(f"  {_SKIP}  {label}")


# ── Individual tests ──────────────────────────────────────────────────────────

def test_env_vars() -> bool:
    _section(1, "Environment Variables")
    required = {
        "EURI_API_KEY":       "Euri API key for GPT-4o",
        "TELEGRAM_BOT_TOKEN": "Telegram bot token from @BotFather",
        "TELEGRAM_CHAT_ID":   "Target chat / channel / group ID",
        "SUPABASE_URL":       "Supabase project URL",
        "SUPABASE_KEY":       "Supabase service-role key",
    }
    ok = True
    for key, desc in required.items():
        val = os.environ.get(key, "")
        if val:
            masked = val[:6] + "…" + val[-4:] if len(val) > 12 else "***"
            _ok(key, f"{desc}  [{masked}]")
        else:
            _err(key, Exception(f"not set — {desc}"))
            ok = False
    return ok


def test_supabase() -> bool:
    _section(2, "Supabase Connection")
    try:
        from supabase import create_client
        db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

        tables = {
            "papers":      "arxiv_id",
            "fetch_logs":  "run_id",
            "fetch_state": "id",
        }
        for table, col in tables.items():
            r = db.table(table).select(col).limit(1).execute()
            _ok(f"{table} table reachable", f"{len(r.data)} row(s) sampled")

        return True
    except Exception as exc:
        _err("Supabase", exc)
        return False


def test_euri_api() -> bool:
    _section(3, "Euri API  (GPT-4o)")
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=os.environ["EURI_API_KEY"],
            base_url="https://api.euron.one/api/v1/euri",
        )
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "Reply with exactly one word: CONNECTED"}],
            max_tokens=10,
            temperature=0,
        )
        reply = resp.choices[0].message.content.strip()
        _ok("GPT-4o response received", repr(reply))
        return True
    except Exception as exc:
        _err("Euri API", exc)
        return False


async def _telegram_check(skip_send: bool) -> bool:
    from telegram import Bot
    try:
        bot  = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
        info = await bot.get_me()
        _ok("Bot authenticated", f"@{info.username}  (id={info.id})")

        if skip_send:
            _skip("Test message skipped  (--skip-send)")
        else:
            chat_id = os.environ["TELEGRAM_CHAT_ID"]
            msg = await bot.send_message(
                chat_id=chat_id,
                text=(
                    "🔧 *AI Papers Agent* — connection test ✅\n"
                    "_If you can read this, Telegram is wired up correctly\\._"
                ),
                parse_mode="MarkdownV2",
            )
            _ok("Test message sent", f"chat_id={chat_id}  message_id={msg.message_id}")

        await bot.close()
        return True
    except Exception as exc:
        _err("Telegram", exc)
        return False


def test_telegram(skip_send: bool) -> bool:
    _section(4, "Telegram Bot")
    return asyncio.run(_telegram_check(skip_send))


def test_arxiv() -> bool:
    _section(5, "ArXiv Paper Fetch")
    try:
        from fetcher import fetch_latest
        papers = fetch_latest(count=1, skip_ids=set())
        if not papers:
            _err("ArXiv", Exception("No papers returned — check network connectivity"))
            return False

        p   = papers[0]
        pub = (p["date_published"].strftime("%d %b %Y")
               if hasattr(p["date_published"], "strftime")
               else str(p["date_published"]))
        _ok("Paper fetched", p["arxiv_id"])
        print(f"         Title:   {p['title'][:65]}{'…' if len(p['title']) > 65 else ''}")
        print(f"         Authors: {p['authors'][:60]}")
        print(f"         Date:    {pub}")
        return True
    except Exception as exc:
        _err("ArXiv", exc)
        return False


async def _e2e(skip_send: bool) -> bool:
    from fetcher import fetch_latest
    from explainer import generate_explanation
    from telegram_bot import format_paper_message, format_digest_header, send_long_message
    from telegram import Bot

    try:
        # Step A — fetch
        papers = fetch_latest(count=1, skip_ids=set())
        if not papers:
            _err("Fetch", Exception("ArXiv returned no papers"))
            return False
        paper = papers[0]
        _ok("Paper fetched", paper["arxiv_id"])

        # Step B — explain
        explanation = generate_explanation(
            title=paper["title"],
            abstract=paper["abstract"],
            authors=paper.get("authors", ""),
        )
        paper.update(explanation)
        _ok(
            "GPT-4o explanation generated",
            f"{len(paper.get('plain_summary', ''))} chars"
            f"  topics={paper.get('topics', [])}",
        )

        # Step C — format
        header_text = format_digest_header([paper], triggered_by="command")
        paper_text  = format_paper_message(paper)
        _ok(
            "Messages formatted",
            f"header={len(header_text)} chars  paper={len(paper_text)} chars",
        )

        # Step D — send
        if skip_send:
            _skip("Telegram send skipped  (--skip-send)")
        else:
            bot     = Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
            chat_id = os.environ["TELEGRAM_CHAT_ID"]
            await send_long_message(bot, chat_id, header_text)
            await send_long_message(bot, chat_id, paper_text)
            await bot.close()
            _ok("Paper sent to Telegram", "check your chat!")

        print(f"\n  ⚠️  Note: this paper was NOT written to Supabase (dry run).")
        return True

    except Exception as exc:
        _err("End-to-end", exc)
        return False


def test_end_to_end(skip_send: bool) -> bool:
    _section(6, "End-to-End: Fetch → Explain → Send  (no DB write)")
    return asyncio.run(_e2e(skip_send))


# ── Runner ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Papers Agent — integration test suite"
    )
    parser.add_argument(
        "--skip-send",
        action="store_true",
        help="Skip sending Telegram messages (still verifies auth)",
    )
    args = parser.parse_args()

    bar = "═" * 58
    print(f"\n{_bold(bar)}")
    print(_bold("  AI Papers Agent — Integration Tests"))
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if args.skip_send:
        print(f"  Mode: {_yellow('--skip-send')} (no Telegram messages will be sent)")
    print(_bold(bar))

    steps = [
        ("Environment Variables",   lambda: test_env_vars()),
        ("Supabase",                lambda: test_supabase()),
        ("Euri API",                lambda: test_euri_api()),
        ("Telegram",                lambda: test_telegram(args.skip_send)),
        ("ArXiv Fetch",             lambda: test_arxiv()),
        ("End-to-End",              lambda: test_end_to_end(args.skip_send)),
    ]

    results: dict[str, bool] = {}
    for name, fn in steps:
        results[name] = fn()

    # Summary
    passed = sum(results.values())
    total  = len(results)
    print(f"\n{_bold(bar)}")
    print(_bold(f"  SUMMARY  —  {passed}/{total} passed"))
    print(_bold(bar))
    for name, ok in results.items():
        icon = _green("✅") if ok else _red("❌")
        print(f"  {icon}  {name}")

    if passed < total:
        print(f"\n  ⚠️  Fix the {total - passed} failing step(s) before deploying.\n")
        sys.exit(1)
    else:
        print(f"\n  🚀  All tests passed — ready to deploy!\n")


if __name__ == "__main__":
    main()
