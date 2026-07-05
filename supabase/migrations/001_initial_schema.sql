-- ============================================================
-- HCIP Ingestion Pipeline — Initial Supabase Schema
-- Run this in: Supabase Dashboard → SQL Editor → New Query
-- ============================================================

-- ── Documents ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS documents (
    document_id         TEXT        PRIMARY KEY,
    organization_id     TEXT        NOT NULL,
    department_id       TEXT        NOT NULL,
    knowledge_base_id   TEXT        NOT NULL,
    file_name           TEXT        NOT NULL,
    file_type           TEXT        NOT NULL,
    s3_key              TEXT        NOT NULL,
    file_size_bytes     BIGINT      NOT NULL DEFAULT 0,
    uploaded_by         TEXT        NOT NULL,
    document_type       TEXT,
    governance_state    TEXT        NOT NULL DEFAULT 'draft',
    processing_status   TEXT        NOT NULL DEFAULT 'pending',
    version_number      INTEGER     NOT NULL DEFAULT 1,
    parent_document_id  TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_documents_org    ON documents (organization_id);
CREATE INDEX idx_documents_kb     ON documents (organization_id, knowledge_base_id);
CREATE INDEX idx_documents_status ON documents (processing_status);
CREATE INDEX idx_documents_gov    ON documents (governance_state);

-- ── Document versions ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS document_versions (
    version_id      TEXT        PRIMARY KEY,
    document_id     TEXT        NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    version_number  INTEGER     NOT NULL,
    s3_key          TEXT        NOT NULL,
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_by      TEXT        NOT NULL,
    change_summary  TEXT        NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, version_number)
);

CREATE INDEX idx_versions_doc    ON document_versions (document_id);
CREATE INDEX idx_versions_active ON document_versions (document_id, is_active);

-- ── Ingestion jobs ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    job_id          TEXT        PRIMARY KEY,
    document_id     TEXT        NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    organization_id TEXT        NOT NULL,
    stage           TEXT        NOT NULL DEFAULT 'upload',
    status          TEXT        NOT NULL DEFAULT 'pending',
    retry_count     INTEGER     NOT NULL DEFAULT 0,
    error_message   TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_jobs_doc    ON ingestion_jobs (document_id);
CREATE INDEX idx_jobs_org    ON ingestion_jobs (organization_id);
CREATE INDEX idx_jobs_status ON ingestion_jobs (status);

-- ── Audit logs ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_logs (
    log_id      TEXT        PRIMARY KEY,
    document_id TEXT        NOT NULL,
    action      TEXT        NOT NULL,
    actor       TEXT        NOT NULL,
    from_state  TEXT,
    to_state    TEXT,
    metadata    JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_doc  ON audit_logs (document_id);
CREATE INDEX idx_audit_time ON audit_logs (created_at DESC);

-- ── Helper RPC: increment job retry counter ───────────────────────────────────
CREATE OR REPLACE FUNCTION increment_job_retry(p_job_id TEXT)
RETURNS VOID AS $$
    UPDATE ingestion_jobs
    SET retry_count = retry_count + 1
    WHERE job_id = p_job_id;
$$ LANGUAGE SQL;

-- ── Row Level Security (enable but keep open for service role) ────────────────
ALTER TABLE documents         ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingestion_jobs    ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs        ENABLE ROW LEVEL SECURITY;

-- Service role bypasses RLS — your SUPABASE_SERVICE_KEY has full access.
-- Add per-user policies here when you add auth (Phase 2 of the project).

-- ── Confirm ───────────────────────────────────────────────────────────────────
SELECT 'Schema created successfully' AS status;
