# AI Papers Agent 🤖

Fetches, explains, and delivers the latest AI research papers from ArXiv to
Telegram — automated entirely with **GitHub Actions** and **Supabase**.
No server. No hosting bill. No always-on process.

```
GitHub Actions (cron / manual)
       │
       ├─► ArXiv API  →  fetch papers
       ├─► Euri API   →  GPT-4o explanation + relevance score
       ├─► Supabase   →  dedup + store
       └─► Telegram   →  send papers scoring 7+/10
```

---

## How it works

| Trigger | What runs |
|---------|-----------|
| Cron — 08:00 UTC daily | `run.py --action fetch` via GitHub Actions |
| Manual dispatch — **fetch** | Same as cron |
| Manual dispatch — **more** | Fetch older papers using cursor |
| Manual dispatch — **today** | List papers already fetched today |
| Manual dispatch — **search** | Search the stored archive by keyword |

Telegram is **output only** — the bot only sends messages, it never listens.

---

## Services you need (all free)

| Service | Role | Sign-up |
|---------|------|---------|
| **GitHub** | Runs the cron job and manual actions | github.com |
| **Supabase** | Stores papers, handles dedup | supabase.com |
| **Telegram** | Receives paper messages | t.me/botfather |
| **Euri API** | GPT-4o for explanations + scoring | euron.one |

---

## Setup — 5 steps

### Step 1 — Supabase

1. Go to **supabase.com** → create a new project
2. Left sidebar → **SQL Editor** → **New query**
3. Paste the entire contents of `schema.sql` → click **Run**
4. Left sidebar → **Project Settings** → **API**
   - Copy **Project URL** (`https://xxxx.supabase.co`)
   - Copy the **service_role** key (long JWT, not the anon key)

> Use the **service_role** key — it bypasses Row Level Security so the bot
> can write to the database.

---

### Step 2 — Telegram bot

1. Open Telegram → search **@BotFather** → send `/newbot`
2. Pick a name and a username ending in `bot`
3. Copy the token BotFather sends (`123456789:ABCdef…`)
4. Get your Chat ID:
   - Send any message to your new bot
   - Visit `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Find `"chat":{"id":` — that number is your Chat ID
   - Channel IDs look like `-1001234567890`

---

### Step 3 — Euri API key

1. Go to **euron.one** → sign up
2. Dashboard → **API Keys** → create a new key

---

### Step 4 — Fork / push to GitHub

```bash
git remote set-url origin https://github.com/YOUR_USERNAME/ai-papers-agent.git
git push -u origin main
```

---

### Step 5 — Add GitHub Secrets

In your GitHub repo → **Settings** → **Secrets and variables** → **Actions**
→ **New repository secret** — add all five:

| Secret name | Value |
|-------------|-------|
| `EURI_API_KEY` | Your Euri key |
| `TELEGRAM_BOT_TOKEN` | Token from BotFather |
| `TELEGRAM_CHAT_ID` | Your chat/channel numeric ID |
| `SUPABASE_URL` | `https://xxxx.supabase.co` |
| `SUPABASE_KEY` | Your service-role JWT |

That's it — the cron job starts running automatically at 08:00 UTC.

---

## Running actions manually

Go to your repo → **Actions** → **AI Papers** → **Run workflow**:

| Action | What it does |
|--------|-------------|
| `fetch` | Fetch the 5 newest AI papers not already in the archive |
| `more` | Fetch 5 older papers (moves the cursor back in time) |
| `today` | List all papers fetched today |
| `search` | Search stored papers — fill in the **Search keyword** field |

For `search`, type a keyword in the **Search keyword** box before clicking
**Run workflow**.

---

## How deduplication and the cursor work

```
fetch  →  scan newest ArXiv papers  →  skip stored IDs  →  take first 5
              │
              └─► cursor = oldest date_published in this batch

more   →  query ArXiv BEFORE cursor date  →  skip stored IDs  →  take first 5
              │
              └─► cursor moves further back
```

The same paper is never fetched twice regardless of how many times you run
`fetch` or `more`.

---

## Relevance scoring

Every paper is scored 1–10 by GPT-4o for relevance to LLMs, agents, RAG,
reasoning, and fine-tuning:

| Score | Meaning | Sent to Telegram? |
|-------|---------|-------------------|
| 7–10 | Clearly or directly relevant | ✅ Yes |
| 4–6 | Adjacent topic | ❌ No — stored only |
| 1–3 | Tangential | ❌ No — stored only |

All papers are stored in Supabase regardless of score.

---

## Local testing

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your five values

# Run the test suite (no Telegram send)
python test_run.py --skip-send

# Run any action locally
python run.py --action fetch
python run.py --action search --query "chain of thought"
```

---

## Project structure

```
├── run.py            GitHub Actions entry point — handles all four actions
├── fetcher.py        ArXiv search with dedup and date-cursor logic
├── explainer.py      GPT-4o explanation, contributions, pseudo-code, scoring
├── telegram_bot.py   MarkdownV2 formatting helpers and send utilities
├── database.py       Supabase CRUD — store, search, cursor, logs
│
├── .github/
│   └── workflows/
│       ├── papers.yml   Daily cron + manual dispatch workflow
│       └── test.yml     Connection tests on every push to main
│
├── schema.sql        Supabase schema — paste into SQL Editor once
├── test_run.py       Integration test suite
├── .env.example      Template for local development
└── requirements.txt
```

---

## Troubleshooting

**Action fails immediately**
- Check **Actions → Run → logs** for the failing step
- Most common cause: a secret is missing or has extra whitespace

**No papers sent but action shows success**
- Papers were fetched but scored below 7/10 — they are stored but not sent
- Run `more` to look further back, or check Supabase `papers` table

**`more` reports "no cursor found"**
- Run `fetch` first at least once to set the cursor

**Test workflow fails**
- Secrets must be added to the repo before the test workflow can pass
- Go to Settings → Secrets → Actions and verify all five secrets exist

**Supabase errors**
- Confirm you ran the full `schema.sql` (all three tables must exist)
- Use the **service_role** key, not the anon key
