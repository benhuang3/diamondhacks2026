-- 002_competitors.sql: competitor_jobs + competitor_results
-- Reference only. Runtime uses SQLAlchemy Base.metadata.create_all().

CREATE TABLE IF NOT EXISTS competitor_jobs (
    id              TEXT PRIMARY KEY,
    store_url       TEXT NOT NULL,
    custom_prompt   TEXT,
    product_hint    TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    progress        REAL NOT NULL DEFAULT 0.0,
    report_id       TEXT,
    error           TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS competitor_results (
    id              TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL REFERENCES competitor_jobs(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    url             TEXT NOT NULL,
    price           REAL,
    shipping        REAL,
    tax             REAL,
    discount        TEXT,
    checkout_total  REAL,
    raw_data        TEXT,   -- JSON
    notes           TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_competitor_results_job_id ON competitor_results(job_id);
CREATE INDEX IF NOT EXISTS idx_competitor_jobs_status ON competitor_jobs(status);
