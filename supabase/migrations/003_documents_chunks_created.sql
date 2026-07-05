-- Adds a column the lightweight /ingest/upload endpoint needs to report chunk
-- counts back to the frontend document list, without requiring a join to Qdrant.

ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunks_created INTEGER NOT NULL DEFAULT 0;
