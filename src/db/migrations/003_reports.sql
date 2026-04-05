-- 003_reports.sql: reports
-- Reference only. Runtime uses SQLAlchemy Base.metadata.create_all().

CREATE TABLE IF NOT EXISTS reports (
    id               TEXT PRIMARY KEY,
    kind             TEXT NOT NULL,      -- scan|competitors
    parent_id        TEXT NOT NULL,      -- scan_id or job_id
    scores           TEXT NOT NULL,      -- JSON
    summary          TEXT NOT NULL,
    sections         TEXT NOT NULL,      -- JSON
    recommendations  TEXT NOT NULL,      -- JSON
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reports_parent_id ON reports(parent_id);
CREATE INDEX IF NOT EXISTS idx_reports_kind ON reports(kind);
