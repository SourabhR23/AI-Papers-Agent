# AI Papers Agent 🤖

Fetches, explains, and delivers the latest AI research papers to Telegram —
automated entirely with **GitHub Actions** and **Supabase**.
No server. No hosting. No webhook.

```
Every 5 min: GitHub Actions → getUpdates → execute command → Telegram
Every 8am:   GitHub Actions → fetch papers → Telegram
                                    │
                               Supabase DB (dedup · store · search)
```

---

## How it works

### Command polling

A GitHub Actions workflow runs **every 5 minutes**. It calls Telegram's
`getUpdates` API to check for new bot messages. If a command was sent to the
bot in the last 15 minutes it executes it and sends the result back.

The last processed `update_id` is stored in Supabase so each command is
executed **exactly once**, even across concurrent runs.

### Daily auto-fetch

A separate workflow runs at **08:00 UTC every day** and automatically fetches
the 4–5 newest AI papers without any command needed.

### Telegram

The bot only **sends** messages — it never runs a polling loop or webhook.
Commands go in via the Telegram chat; results come back via the Bot API.

---

## Commands

| Command | What it does |
|---------|-------------|
| `/fetch` | Fetch 4–5 newest AI papers not already in Supabase |
| `/more` | Fetch 4–5 older papers (cursor moves back each time) |
| `/today` | List all papers fetched today with titles and links |
| `/search <keyword>` | Search the stored archive by topic |
| `/trends` | Top trending AI topics from this week's papers |
| `/ask <question>` | Answer a question from stored paper summaries |
| `/status` | Total papers stored and last fetch info |
| `/help` | List all commands |

> **Latency**: commands execute within ~5 minutes of being sent.

---

## Services (all free)

| Service | Role |
|---------|------|
| **GitHub Actions** | Cron scheduler — runs poll.py and run.py |
| **Supabase** | Stores papers, dedup via `arxiv_id`, persists Telegram offset |
| **Telegram** | Delivers paper summaries to your chat |
| **Euri API** | GPT-4o for explanations and relevance scoring |

---

## Setup — 5 steps

### Step 1 — Supabase

1. Go to **supabase.com** → create a new project
2. Left sidebar → **SQL Editor** → **New query**
3. Paste the full contents of `schema.sql` → click **Run**
   - Creates `papers`, `fetch_logs`, `fetch_state` tables
   - Adds the `telegram_offset` column used by the poller
4. Left sidebar → **Project Settings** → **API**
   - Copy **Project URL** (`https://xxxx.supabase.co`)
   - Copy the **service_role** key (the long JWT — not the anon key)

---

### Step 2 — Telegram bot

1. Open Telegram → search **@BotFather** → send `/newbot`
2. Pick a name and a username ending in `bot`
3. Copy the token BotFather sends (`123456789:ABCdef…`)
4. **Get your Chat ID** — send any message to your new bot, then visit:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
   Find `"chat":{"id":` — that number is your Chat ID.
   (Channel IDs are negative like `-1001234567890`)

---

### Step 3 — Euri API key

1. Go to **euron.one** → sign up
2. Dashboard → **API Keys** → create a new key

---

### Step 4 — Push to GitHub

```bash
git remote set-url origin https://github.com/YOUR_USERNAME/ai-papers-agent.git
git push -u origin main
```

---

### Step 5 — Add GitHub Secrets

Repo → **Settings** → **Secrets and variables** → **Actions** →
**New repository secret** — add all five:

| Secret | Value |
|--------|-------|
| `EURI_API_KEY` | Your Euri key |
| `TELEGRAM_BOT_TOKEN` | Token from BotFather |
| `TELEGRAM_CHAT_ID` | Your chat/channel numeric ID |
| `SUPABASE_URL` | `https://xxxx.supabase.co` |
| `SUPABASE_KEY` | Your service-role JWT |

Once the secrets are saved and the code is pushed, GitHub Actions picks up
both workflows automatically — no further configuration needed.

---

## How dedup and the cursor work

```
/fetch  →  scan newest ArXiv papers  →  skip arxiv_ids already in Supabase
              └─► store all papers  →  cursor = oldest date_published seen

/more   →  query ArXiv BEFORE cursor date  →  skip stored IDs
              └─► store new papers  →  cursor moves further back
```

The same paper is never fetched or sent twice.

---

## Relevance scoring

GPT-4o scores each paper 1–10 for relevance to LLMs, agents, RAG, reasoning,
and fine-tuning. Only papers scoring **7+** are sent to Telegram; all papers
are stored in Supabase regardless.

---

## Local testing

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your five values

python test_run.py --skip-send   # verify all API connections

python poll.py                   # simulate one poll cycle
python run.py --action fetch     # run daily fetch manually
```

---

## Project structure

```
├── poll.py           Telegram poller — run every 5 min by GitHub Actions
├── run.py            Direct action runner — used by the daily workflow
│
├── fetcher.py        ArXiv search with dedup and date-cursor logic
├── explainer.py      GPT-4o explanation, contributions, pseudo-code, scoring
├── telegram_bot.py   MarkdownV2 formatters and send utilities
├── database.py       Supabase CRUD — papers, cursor, offset, status
│
├── .github/
│   └── workflows/
│       ├── poll.yml    Runs every 5 min — checks Telegram for commands
│       ├── daily.yml   Runs at 08:00 UTC — auto daily fetch
│       └── test.yml    Runs on push to main — verifies API connections
│
├── schema.sql        Full Supabase schema — paste into SQL Editor once
├── test_run.py       Integration test suite
├── .env.example      Template for local development
└── requirements.txt
```

---

## Troubleshooting

**Commands aren't executing**
- GitHub Actions free tier can delay cron jobs. Check Actions tab for queued runs.
- Confirm all 5 secrets are set under repo Settings → Secrets → Actions.
- Check the poll workflow run log for the specific error.

**"No cursor found" after /more**
- Run `/fetch` at least once first to establish the cursor.

**No papers sent but run succeeded**
- Papers scored below 7/10 are stored but not sent. Try `/more` to go further back,
  or check the Supabase `papers` table to confirm they were stored.

**Supabase errors**
- Make sure you ran the full `schema.sql` (all tables + the `telegram_offset` migration).
- Use the **service_role** key, not the anon key.

**Test workflow fails on push**
- Secrets must exist for the test to pass. Add them before the first push,
  or re-run the workflow after adding them.
