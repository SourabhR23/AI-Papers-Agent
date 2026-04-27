# AI Papers Agent 🤖

A fully automated Telegram bot that fetches, explains, and archives the latest
AI research papers from ArXiv every day — powered by GPT-4o and Supabase.
Deploy in under 10 minutes from your phone using Railway's free tier.

```
ArXiv ──► Fetcher ──► GPT-4o Explainer ──► Telegram Bot
                            │
                       Supabase DB  (dedup · archive · search)
```

---

## What it does

| Feature | Detail |
|---------|--------|
| 📥 Daily fetch | 4-5 newest AI papers at 08:00 UTC via APScheduler |
| 🧠 AI explanation | GPT-4o writes a plain-English summary, key contributions, and pseudo-code |
| 📬 Telegram delivery | Beautifully formatted MarkdownV2 messages with ArXiv links |
| 🗄️ Dedup storage | Papers stored in Supabase — same paper never sent twice |
| ⏮ Backwards paging | `/more` uses a date cursor to go further back each time |
| 🔍 Search | `/search <topic>` queries your stored archive |

---

## Services you need (all have free tiers)

| Service | Free tier | Sign-up URL |
|---------|-----------|-------------|
| **Supabase** | 500 MB database, unlimited API calls | supabase.com |
| **Railway** | $5 free credit / month (plenty for a bot) | railway.app |
| **Telegram** | Free | t.me/botfather |
| **Euri API** | Pay-per-use GPT-4o | euron.one |

---

## Step 1 — Supabase Setup

### 1.1 Create a project

1. Go to **supabase.com** → **Start your project** → sign in with GitHub
2. Click **New project**
3. Fill in:
   - **Project name**: `ai-papers-agent` (or anything)
   - **Database password**: generate a strong one and save it somewhere
   - **Region**: pick the closest to you
4. Click **Create new project** — takes ~2 minutes to spin up

### 1.2 Run the schema

1. In the left sidebar click **SQL Editor**
2. Click **New query** (top-left of the editor panel)
3. Open `schema.sql` from this repo and **paste the entire file** into the editor
4. Click **Run** (▶ button) or press `Ctrl+Enter`

You should see three green confirmation rows in the results pane confirming the
tables (`papers`, `fetch_logs`, `fetch_state`) were created.

### 1.3 Copy your credentials

1. Left sidebar → **Project Settings** → **API**
2. Copy two values:
   - **Project URL** — looks like `https://abcdefgh.supabase.co`
   - **service_role** key (scroll down past the anon key) — long JWT starting with `eyJ…`

> ⚠️ Use the **service_role** key, not the anon key. The service role bypasses
> Row Level Security and is required for the bot to write to the database.

---

## Step 2 — Telegram Bot Setup

### 2.1 Create the bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a display name (e.g. `AI Papers Daily`)
4. Choose a username ending in `bot` (e.g. `aipapers_yourname_bot`)
5. BotFather replies with a token like `123456789:ABCdef…` — **copy it**

### 2.2 Get your Chat ID

You need the numeric ID of the chat where the bot will post.

**Option A — personal chat (simplest)**

1. Send any message to your new bot
2. Visit this URL in your browser (replace `TOKEN`):
   ```
   https://api.telegram.org/botTOKEN/getUpdates
   ```
3. Find `"chat":{"id":` in the JSON — that number is your Chat ID

**Option B — a channel**

1. Create a channel in Telegram
2. Add your bot as an **Administrator** with "Post Messages" permission
3. Forward any channel message to **@userinfobot** — it shows the channel's Chat ID
   (channel IDs look like `-1001234567890`)

**Option C — a group**

1. Create a group, add your bot
2. Send a message in the group, then hit the `/getUpdates` URL above
3. The `chat.id` in the response is a negative number like `-987654321`

---

## Step 3 — Euri API Key

1. Go to **euron.one** → sign up
2. Dashboard → **API Keys** → create a new key
3. Copy the key (starts with something like `euri-…`)

---

## Step 4 — Push to GitHub

Railway deploys from a GitHub repo. If you cloned this repo, you already have
the code. Just make sure it is pushed to your GitHub account:

```bash
git remote set-url origin https://github.com/YOUR_USERNAME/ai-papers-agent.git
git push -u origin main
```

If starting fresh:

```bash
# On GitHub: create a new empty repo called ai-papers-agent
git remote add origin https://github.com/YOUR_USERNAME/ai-papers-agent.git
git push -u origin main
```

---

## Step 5 — Deploy to Railway

### 5.1 Create a Railway project

1. Go to **railway.app** → log in with GitHub
2. Click **New Project**
3. Select **Deploy from GitHub repo**
4. Authorise Railway to access your repositories if prompted
5. Select your **ai-papers-agent** repo
6. Railway detects the `Dockerfile` automatically and queues a build

### 5.2 Set environment variables

Before the first deploy succeeds you need to add all five environment variables.

1. In your Railway project, click the service card (the box with your repo name)
2. Click the **Variables** tab
3. Click **New Variable** for each of the following:

| Variable name | Value |
|---------------|-------|
| `EURI_API_KEY` | Your Euri key |
| `TELEGRAM_BOT_TOKEN` | Token from BotFather |
| `TELEGRAM_CHAT_ID` | Your chat/channel numeric ID |
| `SUPABASE_URL` | `https://xxxx.supabase.co` |
| `SUPABASE_KEY` | Your service-role JWT |

4. Railway automatically redeploys when variables are saved

### 5.3 Confirm deployment

1. Click the **Deployments** tab
2. Watch the build log — a successful deploy ends with:
   ```
   Starting AI Papers Agent…
   APScheduler started — daily fetch job scheduled for 08:00 UTC
   ```
3. The bot is now live 🎉

---

## Step 6 — Test everything

### Quick test from your machine

```bash
# clone and install locally just for testing
git clone https://github.com/YOUR_USERNAME/ai-papers-agent.git
cd ai-papers-agent
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# copy env template and fill it in
cp .env.example .env
# edit .env with your five values

# run the integration test suite
python test_run.py
```

Expected output when everything is working:

```
══════════════════════════════════════════════════════════
  AI Papers Agent — Integration Tests
  2026-04-27 09:00:00
══════════════════════════════════════════════════════════

──────────────────────────────────────────────────────────
  1. Environment Variables
──────────────────────────────────────────────────────────
  PASS  EURI_API_KEY        (euri-k…3f9a)
  PASS  TELEGRAM_BOT_TOKEN  (123456…0bot)
  PASS  TELEGRAM_CHAT_ID    (your chat ID)
  PASS  SUPABASE_URL        (https://…)
  PASS  SUPABASE_KEY        (eyJhbG…)

  ... (further steps) ...

══════════════════════════════════════════════════════════
  SUMMARY  —  6/6 passed
══════════════════════════════════════════════════════════
  ✅  Environment Variables
  ✅  Supabase
  ✅  Euri API
  ✅  Telegram
  ✅  ArXiv Fetch
  ✅  End-to-End

  🚀  All tests passed — ready to deploy!
```

Run with `--skip-send` to check everything except the actual Telegram send:

```bash
python test_run.py --skip-send
```

---

## Bot Commands

| Command | What it does |
|---------|-------------|
| `/fetch` | Fetch the 4-5 newest papers not already in your database |
| `/more` | Fetch 4-5 papers older than the current cursor (goes further back each time) |
| `/today` | List all papers fetched today with dates and links |
| `/search <topic>` | Search your stored archive, e.g. `/search chain of thought` |

---

## How the deduplication and cursor work

```
/fetch  →  newest ArXiv papers  →  skip stored IDs  →  take first 5
              │
              └─► update cursor = oldest date_published in this batch

/more   →  query ArXiv BEFORE cursor date  →  skip stored IDs  →  take first 5
              │
              └─► update cursor = oldest date_published in new batch
```

Every call to `/more` moves the cursor further back in time. You will never
receive the same paper twice regardless of how many times you call either command.

---

## Local Development

```bash
# Install dependencies
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env   # fill in your five values

# Verify connections (recommended before first run)
python test_run.py

# Run the bot locally
python main.py
```

The bot starts polling immediately. Trigger a manual fetch with `/fetch` in
Telegram. The automatic daily job fires at **08:00 UTC**.

---

## Project Structure

```
├── main.py           Entry point — bot + APScheduler
├── fetcher.py        ArXiv search with dedup & date-cursor logic
├── explainer.py      GPT-4o explanation, contributions, pseudo-code
├── telegram_bot.py   MarkdownV2 formatting + all command handlers
├── database.py       Supabase CRUD + cursor read/write
├── scheduler.py      Daily 08:00 UTC job
│
├── test_run.py       Integration test suite (run before deploying)
├── schema.sql        Full Supabase schema — paste into SQL Editor
├── Dockerfile        Multi-stage production image
├── railway.toml      Railway deployment config
├── .env.example      Template for all environment variables
└── requirements.txt
```

---

## Environment Variables Reference

| Variable | Where to get it |
|----------|----------------|
| `EURI_API_KEY` | euron.one → Dashboard → API Keys |
| `TELEGRAM_BOT_TOKEN` | Telegram → @BotFather → /newbot |
| `TELEGRAM_CHAT_ID` | See Step 2.2 above |
| `SUPABASE_URL` | Supabase → Project Settings → API → Project URL |
| `SUPABASE_KEY` | Supabase → Project Settings → API → service_role key |

---

## Troubleshooting

**Bot doesn't respond to commands**
- Check Railway → Deployments → latest deploy log for errors
- Confirm `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set correctly
- Make sure the bot is a member of the chat/channel

**Supabase errors on first run**
- Make sure you ran the full `schema.sql` in the SQL Editor (all three tables)
- Confirm you're using the **service_role** key, not the anon key

**GPT-4o call fails**
- Verify `EURI_API_KEY` is valid at euron.one dashboard
- Run `python test_run.py --skip-send` to isolate the failing step

**`/more` says "no cursor found, run /fetch first"**
- Expected — run `/fetch` at least once to establish the starting cursor

**Railway build fails**
- Check that `Dockerfile` and `requirements.txt` are committed and pushed
- Railway logs show the exact pip or Docker error
