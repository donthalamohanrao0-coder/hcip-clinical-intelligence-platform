from __future__ import annotations

import io
import logging
from typing import Optional

from ingestion.config import Settings, get_settings
from ingestion.exceptions import EmbeddingError
from ingestion.storage.s3_storage import S3Storage

logger = logging.getLogger(__name__)

_MODEL_NAME = "vidore/colqwen2-v1.0"
_VECTOR_DIM = 128   # ColQwen2 per-patch dimension; mean-pooled to single vector


class ImageEmbedder:
    """
    Multimodal image embedder using ColQwen2 (128-dim per patch, mean-pooled).

    Used exclusively for FIGURE chunks (charts, forms, medical images).
    The figure's S3 key is stored in `chunk.metadata.section` by FigureChunker;
    this embedder downloads the image bytes and produces a single dense vector.

    Note: Qdrant's image collection (hcip_images) must be created with
    vector_size=128 — different from the text/table collections (1024-dim).

    The ColQwen2 model is a class-level singleton (GPU memory is precious).
    """

    _model     = None
    _processor = None

    def __init__(
        self,
        s3:       Optional[S3Storage] = None,
        settings: Optional[Settings]  = None,
    ) -> None:
        self._s3  = s3
        self._cfg = settings or get_settings()

    # ── Public API ────────────────────────────────────────────────────────────

    def embed_figure(self, s3_key: str) -> Optional[list[float]]:
        """
        Download the figure from S3 and embed it with ColQwen2.
        Returns None when the model is unavailable or the S3 key is empty.
        """
        if not s3_key or not self._s3:
            return None

        image_bytes = self._download(s3_key)
        if image_bytes is None:
            return None

        return self._encode_image(image_bytes)

    def embed_batch(self, s3_keys: list[str]) -> list[Optional[list[float]]]:
        """Embed multiple figures; None is returned for any failed item."""
        return [self.embed_figure(key) for key in s3_keys]

    # ── Model loading ─────────────────────────────────────────────────────────

    @classmethod
    def _load_model(cls):
        if cls._model is not None:
            return cls._model, cls._processor
        try:
            import torch
            from colpali_engine.models import ColQwen2, ColQwen2Processor

            cls._processor = ColQwen2Processor.from_pretrained(_MODEL_NAME)
            cls._model     = ColQwen2.from_pretrained(
                _MODEL_NAME,
                torch_dtype=torch.bfloat16,
                device_map="auto",
            )
            cls._model.eval()
            logger.info("ColQwen2 model loaded (%s)", _MODEL_NAME)
        except ImportError:
            logger.warning(
                "colpali-engine not installed — image embedding disabled. "
                "pip install colpali-engine"
            )
            cls._model     = None
            cls._processor = None
        return cls._model, cls._processor

    # ── Inference ─────────────────────────────────────────────────────────────

    def _encode_image(self, image_bytes: bytes) -> Optional[list[float]]:
        model, processor = self._load_model()
        if model is None or processor is None:
            return None
        try:
            import torch
            from PIL import Image

            pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

            with torch.no_grad():
                batch      = processor.process_images([pil_image]).to(model.device)
                embeddings = model(**batch)           # (1, num_patches, 128)
                # Mean-pool patches → single 128-dim vector
                vector = embeddings[0].mean(dim=0).cpu().float().tolist()

            return vector
        except Exception as exc:
            logger.warning("ColQwen2 inference failed: %s", exc)
            return None

    # ── S3 download ───────────────────────────────────────────────────────────

    def _download(self, s3_key: str) -> Optional[bytes]:
        try:
            return self._s3.download_bytes(s3_key)
        except Exception as exc:
            logger.warning("Failed to download figure s3_key=%s: %s", s3_key, exc)
            return None
