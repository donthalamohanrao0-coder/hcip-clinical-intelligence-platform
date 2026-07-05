from __future__ import annotations

from celery import Celery
from kombu import Queue

from ingestion.config import get_settings


def create_celery_app() -> Celery:
    cfg = get_settings()

    app = Celery(
        "hcip_ingestion",
        broker  = cfg.redis_url,
        backend = cfg.redis_url,
    )
    app.conf.update(
        # Serialization
        task_serializer   = "json",
        result_serializer = "json",
        accept_content    = ["json"],

        # Reliability
        task_track_started          = True,
        task_acks_late              = True,   # ack after completion, not on receipt
        worker_prefetch_multiplier  = 1,      # one task at a time — ML workloads
        task_reject_on_worker_lost  = True,   # re-queue if worker dies mid-task

        # Timeouts (embed_task can be slow on CPU)
        task_time_limit      = 3_600,   # 1 h hard kill
        task_soft_time_limit = 3_300,   # 55 min soft warn

        # Dedicated queues — allows separate worker pools per stage
        task_queues = [
            Queue("parse"),        # CPU — Docling / PaddleOCR
            Queue("enrich"),       # CPU + network — NER, RxNorm, ICD-10
            Queue("chunk"),        # CPU
            Queue("embed"),        # GPU — BGE-M3, ColQwen
            Queue("graph"),        # I/O — Neo4j writes
            Queue("validate_index"),
            Queue("dead_letter"),
        ],
        task_routes = {
            "ingestion.workers.tasks.parse_and_classify_task": {"queue": "parse"},
            "ingestion.workers.tasks.enrich_task":             {"queue": "enrich"},
            "ingestion.workers.tasks.chunk_task":              {"queue": "chunk"},
            "ingestion.workers.tasks.embed_task":              {"queue": "embed"},
            "ingestion.workers.tasks.graph_task":              {"queue": "graph"},
            "ingestion.workers.tasks.validate_and_index_task": {"queue": "validate_index"},
            "ingestion.workers.tasks.handle_dead_letter":      {"queue": "dead_letter"},
        },

        # Retry defaults (overridden per task where needed)
        task_max_retries       = 3,
        task_default_retry_delay = 60,   # seconds
    )
    return app


celery_app = create_celery_app()
