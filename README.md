# AI Papers Agent

A fully automated Telegram bot that fetches, explains, and archives the latest AI research papers from ArXiv every day — powered by GPT-4o and Supabase.

---

## Features

- Fetches 4-5 recent ArXiv papers covering LLMs, agents, RAG, fine-tuning, reasoning, and more
- GPT-4o generates a plain-English explanation, key contributions, and a pseudo-code example for each paper
- Sends richly formatted Telegram messages with one tap to the ArXiv page
- Stores every paper in Supabase — duplicates are never re-sent
- Daily automatic delivery at **08:00 UTC** via APScheduler
- Telegram commands: `/fetch`, `/more`, `/today`, `/search`

---

## Prerequisites

| Service | What you need |
|---------|--------------|
| OpenAI | API key with GPT-4o access |
| Telegram | Bot token from [@BotFather](https://t.me/botfather) + your chat/channel ID |
| Supabase | A free project — URL and anon/service-role key |
| Python | 3.11+ |

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/your-user/ai-papers-agent.git
cd ai-papers-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env and fill in all five values
```

### 3. Create the Supabase table

Open the **SQL Editor** in your Supabase dashboard and run:

```sql
CREATE TABLE papers (
  id            BIGSERIAL PRIMARY KEY,
  paper_id      TEXT        UNIQUE NOT NULL,   -- ArXiv ID, e.g. "2401.12345"
  title         TEXT        NOT NULL,
  authors       TEXT,
  link          TEXT,
  date_published TIMESTAMPTZ,
  date_fetched   TIMESTAMPTZ DEFAULT NOW(),
  summary       TEXT,                          -- GPT-4o explanation
  example       TEXT,                          -- Pseudo-code example
  topics        TEXT[]
);

CREATE INDEX idx_papers_paper_id   ON papers (paper_id);
CREATE INDEX idx_papers_date_fetched ON papers (date_fetched);
```

### 4. Find your Telegram chat ID

Send any message to your bot, then visit:
```
https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
```
Copy the `chat.id` value and put it in `TELEGRAM_CHAT_ID`.

### 5. Run the agent

```bash
python main.py
```

The bot starts polling immediately. The first automatic delivery happens at **08:00 UTC**.

---

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/fetch` | Fetch today's 4-5 newest papers (skips already-stored ones) |
| `/more` | Fetch 4-5 more papers going further back in time |
| `/today` | List every paper already fetched today |
| `/search <topic>` | Search stored papers by keyword, e.g. `/search RAG` |

---

## Project Structure

```
├── main.py          # Entry point — starts bot + scheduler
├── fetcher.py       # ArXiv search and paper extraction
├── explainer.py     # GPT-4o explanation generation
├── telegram_bot.py  # Bot commands and message formatting
├── database.py      # Supabase read/write operations
├── scheduler.py     # APScheduler daily job (08:00 UTC)
├── .env.example     # Template for all required env vars
├── requirements.txt
└── README.md
```

---

## Running with systemd (optional)

```ini
# /etc/systemd/system/ai-papers-agent.service
[Unit]
Description=AI Papers Telegram Agent
After=network.target

[Service]
WorkingDirectory=/opt/ai-papers-agent
ExecStart=/opt/ai-papers-agent/.venv/bin/python main.py
EnvironmentFile=/opt/ai-papers-agent/.env
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ai-papers-agent
```

---

## Running with Docker (optional)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

```bash
docker build -t ai-papers-agent .
docker run -d --env-file .env --name ai-papers-agent ai-papers-agent
```
