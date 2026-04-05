-- 001_init.sql: scans + scan_findings
-- Reference only. Runtime uses SQLAlchemy Base.metadata.create_all().

CREATE TABLE IF NOT EXISTS scans (
    id           TEXT PRIMARY KEY,
    url          TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    progress     REAL NOT NULL DEFAULT 0.0,
    max_pages    INTEGER NOT NULL DEFAULT 5,
    report_id    TEXT,
    error        TEXT,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scan_findings (
    id            TEXT PRIMARY KEY,
    scan_id       TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    selector      TEXT NOT NULL,
    xpath         TEXT,
    bounding_box  TEXT,    -- JSON {x,y,w,h}
    severity      TEXT NOT NULL,  -- high|medium|low
    category      TEXT NOT NULL,  -- a11y|ux|contrast|nav
    title         TEXT NOT NULL,
    description   TEXT NOT NULL,
    suggestion    TEXT NOT NULL,
    page_url      TEXT NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scan_findings_scan_id ON scan_findings(scan_id);
CREATE INDEX IF NOT EXISTS idx_scans_status ON scans(status);
