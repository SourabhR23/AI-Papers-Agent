# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Layer-cache: only re-run pip when requirements change
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim

# Unbuffered output so logs appear immediately in Railway / Docker
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy only the Python source files needed at runtime
COPY database.py explainer.py fetcher.py main.py \
     scheduler.py telegram_bot.py ./

# Non-root user — good practice, required by some registries
RUN useradd -m -u 1000 agent && chown -R agent:agent /app
USER agent

CMD ["python", "main.py"]
