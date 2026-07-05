# HCIP — Credentials & Platform Setup Guide

This guide walks you through setting up every external service the pipeline uses.
Two credentials are still missing from `.env`: **AWS S3** and **Anthropic API key**.
Everything else (Supabase, Qdrant, Neo4j, Redis) is already configured.

---

## Status at a glance

| Service    | Where it runs   | Status in .env        | Action needed          |
|------------|-----------------|-----------------------|------------------------|
| AWS S3     | Cloud (AWS)     | ❌ REPLACE_WITH_…     | Create IAM user + S3 bucket |
| Supabase   | Cloud           | ✅ Already filled in  | Run SQL migration only  |
| Qdrant     | Local Docker    | ✅ No key needed      | `docker-compose up -d` |
| Neo4j      | Local Docker    | ✅ Password set       | `docker-compose up -d` |
| Redis      | Local Docker    | ✅ No password        | `docker-compose up -d` |
| OpenAI     | Cloud (API)     | ❌ REPLACE_WITH_…     | Create API key          |

---

## 1. AWS S3

### 1a. Create an S3 Bucket

1. Go to [https://s3.console.aws.amazon.com](https://s3.console.aws.amazon.com)
2. Click **Create bucket**
3. Bucket name: `hcip-documents` (must be globally unique — add a suffix if taken, e.g. `hcip-documents-abc123`)
4. Region: `us-east-1` (or change `AWS_REGION` in `.env` to match)
5. **Block all public access** → leave ON (default)
6. Click **Create bucket**

### 1b. Create an IAM User with S3-only permissions

1. Go to [https://console.aws.amazon.com/iam](https://console.aws.amazon.com/iam)
2. Left panel → **Users** → **Create user**
3. Username: `hcip-ingestion`
4. Next → **Attach policies directly** → search and attach: **AmazonS3FullAccess**
   (For production: create a custom policy scoped to your bucket only)
5. Click **Create user**

### 1c. Generate Access Keys

1. Click on the newly created user `hcip-ingestion`
2. Tab: **Security credentials** → **Create access key**
3. Use case: **Application running outside AWS** → Next
4. Click **Create access key**
5. **COPY BOTH VALUES NOW** — the secret is shown only once

Paste into `.env`:
```
AWS_ACCESS_KEY_ID=AKIA...your_key_here
AWS_SECRET_ACCESS_KEY=your_secret_here
```

---

## 2. Supabase — Run the SQL Migration

Your Supabase project is already created. You just need to create the 4 tables.

1. Open [https://app.supabase.com](https://app.supabase.com)
2. Select your project: `uoeofjrnjzlvkbzmgssn`
3. Left sidebar → **SQL Editor** → **New query**
4. Open the file `supabase/migrations/001_initial_schema.sql` in this project
5. Copy the entire content and paste it into the SQL editor
6. Click **Run** (or Ctrl+Enter)
7. You should see: `Schema created successfully`

To verify, go to **Table Editor** — you should see 4 tables:
- `documents`
- `document_versions`
- `ingestion_jobs`
- `audit_logs`

---

## 3. Qdrant (Local Docker)

No account or API key needed for local development.

```bash
# Start Qdrant (from the project root)
docker-compose up -d qdrant

# Verify it's running
curl http://localhost:6333/readyz
# Expected output: {"status":"ok"}

# Open the web UI (optional)
# Browser: http://localhost:6333/dashboard
```

The `.env` values are already correct:
```
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_API_KEY=          ← blank = no auth (local only)
```

**If you want Qdrant Cloud instead (free tier):**
1. Sign up at [https://cloud.qdrant.io](https://cloud.qdrant.io)
2. Create a free cluster (1 GB, 1 node)
3. Copy the **Cluster URL** and **API Key**
4. Update `.env`:
   ```
   QDRANT_HOST=your-cluster-id.us-east-1-0.aws.cloud.qdrant.io
   QDRANT_PORT=6333
   QDRANT_API_KEY=your_qdrant_api_key
   ```

---

## 4. Neo4j (Local Docker)

No account needed for local development.

```bash
# Start Neo4j (from the project root)
docker-compose up -d neo4j

# Wait ~30 seconds for startup, then open the browser UI
# Browser: http://localhost:7474
# Login: neo4j / hcip_password
```

The `.env` values match the `docker-compose.yml` password:
```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=hcip_password
```

**If you want Neo4j AuraDB Free instead (cloud, no Docker):**
1. Sign up at [https://neo4j.com/cloud/platform/aura-graph-database/](https://neo4j.com/cloud/platform/aura-graph-database/)
2. Create a **Free instance** (AuraDB Free)
3. Download the connection file — it contains your URI, username, and password
4. Update `.env`:
   ```
   NEO4J_URI=neo4j+s://xxxxxxxx.databases.neo4j.io
   NEO4J_USER=neo4j
   NEO4J_PASSWORD=your_aura_password
   ```

---

## 5. Redis (Local Docker)

No account or password needed for local development.

```bash
# Start Redis (from the project root)
docker-compose up -d redis

# Verify
docker exec hcip_redis redis-cli ping
# Expected: PONG
```

`.env` values are already correct — no changes needed.

---

## 6. OpenAI API Key

1. Go to [https://platform.openai.com/api-keys](https://platform.openai.com/api-keys)
2. Click **Create new secret key**
3. Name: `hcip-ingestion-dev`
4. Copy the key (shown only once — starts with `sk-…`)

Paste into `.env`:
```
OPENAI_API_KEY=sk-...your_key_here
```

**Cost note:** The pipeline uses `gpt-4o-mini` only as a fallback for metadata extraction when regex heuristics fail. Typical cost: < $0.01 per document.

---

## 7. Start all local services at once

```bash
# From the project root (requires Docker Desktop running)
docker-compose up -d

# Check all are healthy
docker-compose ps
```

Expected output:
```
NAME           STATUS          PORTS
hcip_redis     Up (healthy)    0.0.0.0:6379->6379/tcp
hcip_qdrant    Up (healthy)    0.0.0.0:6333->6333/tcp, 0.0.0.0:6334->6334/tcp
hcip_neo4j     Up (healthy)    0.0.0.0:7474->7474/tcp, 0.0.0.0:7687->7687/tcp
```

---

## 8. Install Python dependencies

```bash
# Create virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / Mac

# Install all packages
pip install -r requirements.txt

# Download the spaCy medical NER model
python -m spacy download en_core_sci_sm
# If that fails (not found via pip), run:
pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_core_sci_sm-0.5.4.tar.gz
```

---

## 9. Quick smoke test

After all credentials are in `.env` and Docker is running:

```bash
python - <<'EOF'
from ingestion.config import get_settings
cfg = get_settings()
print("Settings loaded OK")
print(f"  Supabase URL : {cfg.supabase_url}")
print(f"  S3 Bucket    : {cfg.s3_bucket}")
print(f"  Qdrant host  : {cfg.qdrant_host}:{cfg.qdrant_port}")
print(f"  Neo4j URI    : {cfg.neo4j_uri}")
print(f"  Redis URL    : {cfg.redis_url}")
print(f"  Anthropic key: {'set' if cfg.anthropic_api_key else 'MISSING'}")
EOF
```

---

## Summary — what still needs your action

1. **AWS S3**: Create IAM user → generate access keys → paste into `.env`
2. **OpenAI**: Create API key at platform.openai.com/api-keys → paste into `.env`
3. **Supabase**: Run `supabase/migrations/001_initial_schema.sql` in the SQL Editor
4. **Docker services**: `docker-compose up -d` (Redis + Qdrant + Neo4j)
5. **Python deps**: `pip install -r requirements.txt` + spaCy model download
