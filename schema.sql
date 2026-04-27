-- ================================================================
-- AI Papers Agent — Supabase Schema
-- Paste this entire script into: Dashboard → SQL Editor → New query
-- ================================================================


-- ── 1. papers ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS papers (
    arxiv_id          TEXT        PRIMARY KEY,
    title             TEXT        NOT NULL,
    authors           TEXT,
    abstract          TEXT,
    link              TEXT,
    topics            TEXT[]      NOT NULL DEFAULT '{}',
    plain_summary     TEXT,
    key_contributions TEXT,
    code_example      TEXT,
    date_published    TIMESTAMPTZ,
    date_fetched      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  papers                    IS 'ArXiv AI research papers fetched and explained by the agent';
COMMENT ON COLUMN papers.arxiv_id           IS 'ArXiv paper ID without version suffix, e.g. 2401.12345';
COMMENT ON COLUMN papers.topics             IS 'Array of matched topic labels, e.g. {LLMs, agents, RAG}';
COMMENT ON COLUMN papers.plain_summary      IS 'GPT-4o plain English explanation (3–4 paragraphs)';
COMMENT ON COLUMN papers.key_contributions  IS 'GPT-4o bullet-point list of key contributions';
COMMENT ON COLUMN papers.code_example       IS 'GPT-4o pseudo-code or conceptual code snippet';


-- ── 2. fetch_logs ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fetch_logs (
    run_id          BIGSERIAL   PRIMARY KEY,
    run_date        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    papers_fetched  INTEGER     NOT NULL DEFAULT 0,
    triggered_by    TEXT        NOT NULL DEFAULT 'command'
                    CHECK (triggered_by IN ('scheduler', 'command'))
);

COMMENT ON TABLE  fetch_logs                IS 'Audit log of every fetch run';
COMMENT ON COLUMN fetch_logs.triggered_by   IS '"scheduler" = 08:00 UTC daily job | "command" = /fetch or /more';


-- ── 3. Indexes ───────────────────────────────────────────────────

-- arxiv_id is already a B-tree index as PRIMARY KEY.
-- The UNIQUE index below is explicit and used by the Python dedup query.
CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_arxiv_id
    ON papers (arxiv_id);

-- Fast queries for /today (filter on date_fetched DESC)
CREATE INDEX IF NOT EXISTS idx_papers_date_fetched
    ON papers (date_fetched DESC);

-- Fast sorting by publication date
CREATE INDEX IF NOT EXISTS idx_papers_date_published
    ON papers (date_published DESC);

-- GIN index enables efficient array containment queries:
--   SELECT * FROM papers WHERE topics @> ARRAY['RAG']
CREATE INDEX IF NOT EXISTS idx_papers_topics
    ON papers USING GIN (topics);

-- Fast lookup in fetch_logs dashboard/admin queries
CREATE INDEX IF NOT EXISTS idx_fetch_logs_run_date
    ON fetch_logs (run_date DESC);


-- ── 4. Row Level Security ────────────────────────────────────────
--
-- The SUPABASE_KEY in your .env should be the SERVICE ROLE key.
-- The service role bypasses RLS entirely — no policy needed for it.
-- RLS policies below only affect the anon / authenticated JWT roles
-- (e.g. if you ever expose this data through a frontend).
--
-- Rule of thumb:
--   • anon / authenticated  →  read-only SELECT
--   • service_role          →  full INSERT / UPDATE / DELETE (bypasses RLS)

ALTER TABLE papers     ENABLE ROW LEVEL SECURITY;
ALTER TABLE fetch_logs ENABLE ROW LEVEL SECURITY;

-- papers: anyone can read
CREATE POLICY "papers_public_read"
    ON papers
    FOR SELECT
    TO anon, authenticated
    USING (true);

-- papers: only the service role (bot) may write — enforced implicitly
-- because no INSERT/UPDATE/DELETE policy exists for anon/authenticated.

-- fetch_logs: anyone can read run history
CREATE POLICY "fetch_logs_public_read"
    ON fetch_logs
    FOR SELECT
    TO anon, authenticated
    USING (true);


-- ── 5. Sanity-check queries (run after applying schema) ──────────

-- Verify tables exist
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('papers', 'fetch_logs');

-- Verify indexes exist
SELECT indexname, tablename, indexdef
FROM pg_indexes
WHERE tablename IN ('papers', 'fetch_logs')
ORDER BY tablename, indexname;

-- Verify RLS is enabled
SELECT tablename, rowsecurity
FROM pg_tables
WHERE tablename IN ('papers', 'fetch_logs');
