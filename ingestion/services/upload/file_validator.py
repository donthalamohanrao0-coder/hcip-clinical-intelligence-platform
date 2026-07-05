from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ingestion.config import Settings, get_settings
from ingestion.models import FileType


# ── Magic byte signatures ────────────────────────────────────────────────────
# Maps FileType → list of valid byte sequences at offset 0.
# Only binary formats are checked; text formats (CSV, TXT, JSON, XML) are skipped.

_MAGIC: dict[FileType, list[bytes]] = {
    FileType.PDF:  [b"%PDF"],
    FileType.PNG:  [b"\x89PNG\r\n\x1a\n"],
    FileType.JPG:  [b"\xff\xd8\xff"],
    FileType.JPEG: [b"\xff\xd8\xff"],
    FileType.TIFF: [b"II*\x00", b"MM\x00*"],
    # DOCX / PPTX / XLSX are all ZIP archives
    FileType.DOCX: [b"PK\x03\x04"],
    FileType.PPTX: [b"PK\x03\x04"],
    FileType.XLSX: [b"PK\x03\x04"],
}

# File types that accept any content (no binary signature to check)
_TEXT_TYPES: frozenset[FileType] = frozenset({
    FileType.CSV, FileType.TXT, FileType.JSON, FileType.XML, FileType.FHIR,
})

# Minimum readable bytes we inspect for magic
_MAGIC_HEADER_BYTES = 16


# ── Result model ─────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    is_valid:  bool
    file_type: Optional[FileType]
    errors:    list[str] = field(default_factory=list)
    warnings:  list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        """Record an error and mark result invalid."""
        self.errors.append(message)
        self.is_valid = False

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    @property
    def error_summary(self) -> str:
        return "; ".join(self.errors)


# ── Validator ─────────────────────────────────────────────────────────────────

class FileValidator:
    """
    Validates an uploaded file before it enters the ingestion pipeline.

    Checks (in order):
        1. Extension is in the allowed list
        2. File is not empty and does not exceed the size limit
        3. Magic bytes match the declared extension (binary formats only)
        4. Basic content sanity for text formats (valid UTF-8 or printable ASCII)
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._cfg = settings or get_settings()

    def validate(self, filename: str, content: bytes) -> ValidationResult:
        """Run all checks and return a single ValidationResult."""
        result = ValidationResult(is_valid=True, file_type=None)

        file_type = self._check_extension(filename, result)
        if file_type is None:
            return result  # can't continue without a known type

        result.file_type = file_type

        self._check_size(content, result)
        if not result.is_valid:
            return result  # no point inspecting content of an empty/oversized file

        if file_type in _TEXT_TYPES:
            self._check_text_content(content, file_type, result)
        else:
            self._check_magic_bytes(content, file_type, result)

        return result

    # ── Private checks ────────────────────────────────────────────────────────

    def _check_extension(
        self, filename: str, result: ValidationResult
    ) -> Optional[FileType]:
        ext = Path(filename).suffix.lower().lstrip(".")
        if not ext:
            result.fail("File has no extension")
            return None

        if ext not in self._cfg.allowed_extensions:
            result.fail(f"Extension '.{ext}' is not supported")
            return None

        try:
            return FileType.from_extension(ext)
        except ValueError:
            result.fail(f"Extension '.{ext}' could not be mapped to a known file type")
            return None

    def _check_size(self, content: bytes, result: ValidationResult) -> None:
        size = len(content)
        if size == 0:
            result.fail("File is empty")
            return
        limit = self._cfg.max_file_size_bytes
        if size > limit:
            actual_mb = round(size / 1_048_576, 2)
            limit_mb  = self._cfg.max_file_size_mb
            result.fail(
                f"File size {actual_mb} MB exceeds the {limit_mb} MB limit"
            )

    def _check_magic_bytes(
        self, content: bytes, file_type: FileType, result: ValidationResult
    ) -> None:
        signatures = _MAGIC.get(file_type)
        if not signatures:
            return  # no signature registered — skip

        header = content[:_MAGIC_HEADER_BYTES]
        if not any(header.startswith(sig) for sig in signatures):
            result.fail(
                f"File content does not match the expected binary format "
                f"for '{file_type.value}' (magic bytes mismatch)"
            )

    def _check_text_content(
        self, content: bytes, file_type: FileType, result: ValidationResult
    ) -> None:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            result.fail(f"'{file_type.value}' file is not valid UTF-8")
            return

        if file_type == FileType.JSON:
            import json
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                result.fail(f"Invalid JSON: {exc}")

        elif file_type in {FileType.XML, FileType.FHIR}:
            stripped = text.lstrip()
            if not stripped.startswith("<"):
                result.warn("XML/FHIR file does not begin with '<' — may not be valid XML")
