# AI Papers Agent 🤖

A fully automated Telegram bot that fetches, explains, and archives the latest
AI research papers from ArXiv every day — powered by GPT-4o and Supabase.
Deploy in under 15 minutes from your phone using Koyeb's free tier.

```
ArXiv ──► Supabase Edge Function (02:00 UTC)
               │
               ├─► GPT-4o Explainer (Euri API)
               ├─► Supabase DB  (dedup · archive · search)
               └─► Telegram Bot ──► Your Chat
```

---

## What it does

| Feature | Detail |
|---------|--------|
| 📥 Daily fetch | 5 newest AI papers at **02:00 UTC** via Supabase Edge Function cron |
| 🧠 AI explanation | GPT-4o writes a plain-English summary, key contributions, and pseudo-code |
| ⭐ Topic scoring | Papers scored 1–10; only those scoring 7+ are sent to Telegram |
| 📬 Telegram delivery | Beautifully formatted MarkdownV2 messages with ArXiv links |
| 🗄️ Dedup storage | Papers stored in Supabase — same paper never sent twice |
| ⏮ Backwards paging | `/more` uses a date cursor to go further back each time |
| 🔍 Search | `/search <topic>` queries your stored archive |
| 🤖 Q&A | `/ask` answers questions grounded in stored paper summaries |
| 📊 Trends | `/trends` shows the most active AI topics this week |
| 📅 Weekly digest | Top 5 papers of the week sent every Sunday at 09:00 UTC |

---

## Services you need (all have free tiers)

| Service | Free tier | Sign-up |
|---------|-----------|---------|
| **Supabase** | 500 MB database, 500K Edge Function invocations/month | supabase.com |
| **Koyeb** | 1 free nano worker instance (always-on) | koyeb.com |
| **Telegram** | Free | t.me/botfather |
| **Euri API** | Pay-per-use GPT-4o | euron.one |

---

## Step 1 — Supabase Setup

### 1.1 Create a project

1. Go to **supabase.com** → **Start your project** → sign in with GitHub
2. Click **New project**
3. Fill in:
   - **Project name**: `ai-papers-agent`
   - **Database password**: generate a strong one and save it
   - **Region**: pick the closest to you
4. Click **Create new project** — takes ~2 minutes to spin up

### 1.2 Run the schema

1. In the left sidebar click **SQL Editor**
2. Click **New query**
3. Open `schema.sql` from this repo and **paste the entire file** into the editor
4. Click **Run** (▶ button) or press `Ctrl+Enter`

You should see three green confirmation rows confirming `papers`, `fetch_logs`,
and `fetch_state` were created.

### 1.3 Copy your credentials

1. Left sidebar → **Project Settings** → **API**
2. Copy two values:
   - **Project URL** — `https://abcdefgh.supabase.co`
   - **service_role** key (scroll past the anon key) — long JWT starting with `eyJ…`

> ⚠️ Use the **service_role** key, not the anon key. The service role bypasses
> Row Level Security and is required for the bot to write to the database.

### 1.4 Note your Project Reference ID

You need this for the Edge Function in Step 5.

- Left sidebar → **Project Settings** → **General**
- Copy the **Reference ID** (e.g. `abcdefghijklmnop`)

---

## Step 2 — Telegram Bot Setup

### 2.1 Create the bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a display name (e.g. `AI Papers Daily`)
4. Choose a username ending in `bot` (e.g. `aipapers_yourname_bot`)
5. BotFather replies with a token like `123456789:ABCdef…` — **copy it**

### 2.2 Get your Chat ID

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

Both Koyeb and Supabase CLI deploy from GitHub. Push the code first:

```bash
git remote set-url origin https://github.com/YOUR_USERNAME/ai-papers-agent.git
git push -u origin main
```

If starting from scratch:

```bash
# On GitHub: create a new empty repo called ai-papers-agent
git remote add origin https://github.com/YOUR_USERNAME/ai-papers-agent.git
git push -u origin main
```

---

## Step 5 — Supabase Edge Function (Daily Cron at 02:00 UTC)

The Edge Function runs inside Supabase's infrastructure — no extra server needed.
It fetches, explains, scores, and sends papers automatically every night.

### 5.1 Install the Supabase CLI

```bash
# macOS
brew install supabase/tap/supabase

# Windows (scoop)
scoop bucket add supabase https://github.com/supabase/scoop-bucket.git
scoop install supabase

# Linux / manual
curl -s https://raw.githubusercontent.com/supabase/cli/main/scripts/install.sh | bash
```

### 5.2 Link your project

```bash
supabase login
supabase link --project-ref YOUR_PROJECT_REF   # from Step 1.4
```

### 5.3 Update config.toml

Open `supabase/config.toml` and replace `YOUR_PROJECT_REF` with your actual
Reference ID from Step 1.4.

### 5.4 Set Edge Function secrets

The Edge Function needs all five environment variables. Set them as Supabase secrets:

```bash
supabase secrets set EURI_API_KEY=your_euri_key
supabase secrets set TELEGRAM_BOT_TOKEN=123456789:ABCdef...
supabase secrets set TELEGRAM_CHAT_ID=-1001234567890
supabase secrets set SUPABASE_URL=https://your-ref.supabase.co
supabase secrets set SUPABASE_KEY=eyJ...your_service_role_key...
```

> ℹ️ `SUPABASE_URL` and `SUPABASE_KEY` are automatically available inside Edge
> Functions if you use the built-in Supabase client — but setting them
> explicitly as secrets makes the function portable and self-documenting.

### 5.5 Deploy the Edge Function

```bash
supabase functions deploy daily-fetch
```

Verify it appears in the dashboard:
**Supabase Dashboard → Edge Functions → daily-fetch**

The cron schedule (`0 2 * * *`) is read from `supabase/config.toml` and
activated automatically on deploy. You can confirm it under
**Edge Functions → daily-fetch → Schedule**.

### 5.6 Test the Edge Function manually

Trigger a one-shot invocation from the CLI (optional but recommended):

```bash
supabase functions invoke daily-fetch
```

Or hit it from the Supabase dashboard: **Edge Functions → daily-fetch → Invoke**.

---

## Step 6 — Deploy the Bot to Koyeb

The Telegram bot (polling mode) runs as a persistent worker on Koyeb.
It handles all user commands (`/fetch`, `/more`, `/ask`, `/trends`, etc.)
and sends the weekly digest every Sunday — but the daily fetch is fully
delegated to the Edge Function above.

### 6.1 Create a Koyeb account

Go to **koyeb.com** → sign up (GitHub login recommended).

### 6.2 Create a new App

1. Click **Create App**
2. Select **GitHub** as the deployment source
3. Authorise Koyeb to access your repositories if prompted
4. Select your **ai-papers-agent** repo and the `main` branch
5. Under **Build settings**:
   - **Builder**: Dockerfile
   - **Dockerfile path**: `Dockerfile`
6. Under **Service type**: select **Worker** (no HTTP port needed)
7. Under **Instance type**: select **Nano** (free tier)
8. Under **Regions**: pick one close to you (e.g. `was` for Washington DC)

### 6.3 Set environment variables

In the Koyeb service settings → **Environment variables**, add all five:

| Variable name | Value |
|---------------|-------|
| `EURI_API_KEY` | Your Euri key |
| `TELEGRAM_BOT_TOKEN` | Token from BotFather |
| `TELEGRAM_CHAT_ID` | Your chat/channel numeric ID |
| `SUPABASE_URL` | `https://xxxx.supabase.co` |
| `SUPABASE_KEY` | Your service-role JWT |

Mark each as **Secret** so the value is masked in logs.

### 6.4 Deploy

Click **Deploy**. Koyeb builds the Docker image and starts the bot.

A successful deploy shows in the **Logs** tab:

```
Starting AI Papers Agent…
APScheduler started — weekly digest scheduled for Sunday 09:00 UTC
```

The bot is now live 🎉

### 6.5 Using koyeb.yaml (optional)

The repo includes `koyeb.yaml` for CLI-based deployments. After installing the
Koyeb CLI (`curl -sf https://raw.githubusercontent.com/koyeb/koyeb-cli/main/install.sh | sh`):

```bash
# Edit koyeb.yaml: replace YOUR_USERNAME with your GitHub username
koyeb app init ai-papers-agent --manifest koyeb.yaml
```

---

## Step 7 — Test everything

### Quick test from your machine

```bash
# Clone and install locally for testing
git clone https://github.com/YOUR_USERNAME/ai-papers-agent.git
cd ai-papers-agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Copy env template and fill it in
cp .env.example .env
# edit .env with your five values

# Run the integration test suite
python test_run.py
```

Expected output when everything is working:

```
══════════════════════════════════════════════════════════
  AI Papers Agent — Integration Tests
  2026-04-28 09:00:00
══════════════════════════════════════════════════════════

  1. Environment Variables       PASS
  2. Supabase                    PASS
  3. Euri API                    PASS
  4. Telegram                    PASS
  5. ArXiv Fetch                 PASS
  6. End-to-End                  PASS

══════════════════════════════════════════════════════════
  SUMMARY  —  6/6 passed
  🚀  All tests passed — ready to deploy!
══════════════════════════════════════════════════════════
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
| `/ask <question>` | Get a GPT-4o answer grounded in your stored papers |
| `/trends` | Show the most frequently appearing AI topics this week |

---

## Architecture

```
┌──────────────────────────────────────┐
│  Supabase Edge Function              │  ← runs at 02:00 UTC every day
│  supabase/functions/daily-fetch/     │
│    1. GET arxiv papers (ArXiv API)   │
│    2. POST Euri API → GPT-4o score   │
│    3. INSERT into Supabase papers    │
│    4. Advance /more cursor           │
│    5. Send 7+ scored papers via TG   │
└──────────────────┬───────────────────┘
                   │ Supabase DB (shared)
┌──────────────────▼───────────────────┐
│  Koyeb Worker (python main.py)       │  ← always running
│    - Telegram polling loop           │
│    - /fetch /more /today /search     │
│    - /ask /trends                    │
│    - APScheduler: Sunday digest      │
└──────────────────────────────────────┘
```

---

## How deduplication and cursor work

```
/fetch  →  newest ArXiv papers  →  skip stored IDs  →  take first 5
              │
              └─► update cursor = oldest date_published in this batch

/more   →  query ArXiv BEFORE cursor date  →  skip stored IDs  →  take first 5
              │
              └─► update cursor = oldest date_published in new batch
```

The Edge Function and the `/fetch` command both update the same cursor.
Every call to `/more` moves the cursor further back in time — you will never
receive the same paper twice.

---

## Local Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your five values

# Verify all connections
python test_run.py

# Run the bot locally (handles /fetch, /more, etc.)
python main.py
```

The bot starts polling immediately. Trigger a manual fetch with `/fetch` in
Telegram. The automatic daily job fires at **02:00 UTC** via the Edge Function.

---

## Project Structure

```
├── main.py           Entry point — bot + APScheduler (weekly digest)
├── fetcher.py        ArXiv search with dedup & date-cursor logic
├── explainer.py      GPT-4o explanation, contributions, pseudo-code, scoring
├── telegram_bot.py   MarkdownV2 formatting + all command handlers
├── database.py       Supabase CRUD + cursor read/write
├── scheduler.py      Weekly digest job (Sunday 09:00 UTC)
│
├── supabase/
│   ├── config.toml                     Cron schedule for Edge Function
│   └── functions/
│       └── daily-fetch/
│           └── index.ts                Daily fetch Edge Function (02:00 UTC)
│
├── test_run.py       Integration test suite (run before deploying)
├── schema.sql        Full Supabase schema — paste into SQL Editor
├── Dockerfile        Multi-stage production image
├── koyeb.yaml        Koyeb deployment config
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

Set these in:
- **Local dev**: `.env` file (copied from `.env.example`)
- **Koyeb**: Service settings → Environment variables (mark as Secret)
- **Supabase Edge Function**: `supabase secrets set KEY=value`

---

## Troubleshooting

**Bot doesn't respond to commands**
- Check Koyeb → Deployments → Logs for errors
- Confirm `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set correctly
- Make sure the bot is a member of the chat/channel

**Supabase errors on first run**
- Confirm you ran the full `schema.sql` (all three tables must exist)
- Use the **service_role** key, not the anon key

**GPT-4o call fails**
- Verify `EURI_API_KEY` is valid at euron.one dashboard
- Run `python test_run.py --skip-send` to isolate the failing step

**Edge Function not running automatically**
- Confirm `supabase/config.toml` has `schedule = "0 2 * * *"` under `[functions.daily-fetch]`
- Re-deploy with `supabase functions deploy daily-fetch` after editing config
- Check Dashboard → Edge Functions → daily-fetch → Logs

**Edge Function secrets missing**
- Run `supabase secrets list` to see what's set
- Re-run `supabase secrets set KEY=value` for any missing variables

**`/more` says "no cursor found, run /fetch first"**
- Expected — run `/fetch` at least once to establish the starting cursor

**Koyeb build fails**
- Check that `Dockerfile` and `requirements.txt` are committed and pushed
- Koyeb logs show the exact pip or Docker build error
