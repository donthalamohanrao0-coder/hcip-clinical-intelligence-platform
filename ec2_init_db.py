"""
Initialize empty Qdrant collections and Elasticsearch index for HCIP.
Run once after deploying to a fresh server.
"""
import os, sys
sys.path.insert(0, "/home/ubuntu/hcip")
os.environ.setdefault("DOTENV_PATH", "/home/ubuntu/hcip/.env")

from dotenv import load_dotenv
load_dotenv("/home/ubuntu/hcip/.env")

# ── Qdrant: create 3 collections ──────────────────────────────────────────────
print("=== Qdrant collections ===")
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

qc = QdrantClient(host="localhost", port=6333)
collections = {
    "hcip_text":   1024,  # BGE-M3 text embeddings
    "hcip_images": 128,   # ColQwen image embeddings
    "hcip_tables": 1024,  # Table embeddings
    "hcip_query_cache": 1024,  # Query semantic cache
}
for name, dim in collections.items():
    if not qc.collection_exists(name):
        qc.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        print(f"  Created: {name}  ({dim}-dim)")
    else:
        print(f"  Exists:  {name}")

# ── Elasticsearch: create index ───────────────────────────────────────────────
print("\n=== Elasticsearch index ===")
from elasticsearch import Elasticsearch
es = Elasticsearch("http://localhost:9200")
INDEX = "hcip_chunks"
if not es.indices.exists(index=INDEX):
    es.indices.create(
        index=INDEX,
        body={
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {
                "properties": {
                    "chunk_id":          {"type": "keyword"},
                    "document_id":       {"type": "keyword"},
                    "organization_id":   {"type": "keyword"},
                    "knowledge_base_id": {"type": "keyword"},
                    "content":           {"type": "text", "analyzer": "english"},
                    "specialty":         {"type": "keyword"},
                    "document_type":     {"type": "keyword"},
                    "approval_status":   {"type": "keyword"},
                    "risk_level":        {"type": "keyword"},
                }
            },
        },
    )
    print(f"  Created: {INDEX}")
else:
    print(f"  Exists:  {INDEX}")

# ── OpenAI key check ──────────────────────────────────────────────────────────
print("\n=== OpenAI key ===")
key = os.environ.get("OPENAI_API_KEY", "")
if key and not key.startswith("REPLACE"):
    print(f"  Key: {key[:10]}...{key[-4:]}  (loaded OK)")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        models = client.models.list()
        print(f"  API reachable — {len(list(models))} models available")
    except Exception as e:
        print(f"  API error: {e}")
else:
    print("  WARNING: OPENAI_API_KEY not set")

print("\n=== Init complete ===")
