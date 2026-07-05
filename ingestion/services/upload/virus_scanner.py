from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from ingestion.exceptions import VirusScanError

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    is_clean:    bool
    scanner:     str
    threat_name: Optional[str] = None
    scan_time_ms: int = 0

    @property
    def threat_summary(self) -> str:
        return self.threat_name or "no threat detected"


# ── Abstract interface ────────────────────────────────────────────────────────

class BaseVirusScanner(ABC):
    """
    Abstract interface for virus scanning.
    Concrete implementations: StubVirusScanner (dev), ClamAVScanner (prod).
    """

    @abstractmethod
    def scan(self, content: bytes, filename: str) -> ScanResult:
        """
        Scan file content for malware.
        Raises VirusScanError if the scan itself fails (not if a virus is found).
        Returns ScanResult — callers check result.is_clean.
        """


# ── Development stub ──────────────────────────────────────────────────────────

class StubVirusScanner(BaseVirusScanner):
    """
    *** DEVELOPMENT ONLY — always returns clean ***

    Replace with ClamAVScanner or AWSMacieScanner before deploying to production.
    Healthcare data processed by this service may be PHI — real scanning is mandatory.
    """

    def scan(self, content: bytes, filename: str) -> ScanResult:
        logger.warning(
            "StubVirusScanner is active — file '%s' was NOT scanned. "
            "Replace with a real scanner in production.",
            filename,
        )
        return ScanResult(is_clean=True, scanner="stub", scan_time_ms=0)


# ── ClamAV production implementation ──────────────────────────────────────────

class ClamAVScanner(BaseVirusScanner):
    """
    Production virus scanner using a ClamAV daemon (clamd).
    Requires:  pip install clamd
               A running ClamAV daemon accessible at host:port.
    """

    def __init__(self, host: str = "localhost", port: int = 3_310) -> None:
        try:
            import clamd
            self._clamd = clamd.ClamdNetworkSocket(host=host, port=port)
        except ImportError as exc:
            raise ImportError(
                "Install 'clamd' to use ClamAVScanner: pip install clamd"
            ) from exc
        self._host = host
        self._port = port

    def scan(self, content: bytes, filename: str) -> ScanResult:
        import time
        import io
        import clamd

        start = time.monotonic()
        try:
            result = self._clamd.instream(io.BytesIO(content))
        except clamd.ConnectionError as exc:
            raise VirusScanError(
                f"Cannot reach ClamAV at {self._host}:{self._port}: {exc}"
            ) from exc

        elapsed_ms = int((time.monotonic() - start) * 1_000)

        # clamd returns {"stream": ("OK", None)} or {"stream": ("FOUND", "Eicar-Test-Signature")}
        status, threat = result.get("stream", ("OK", None))
        is_clean = status == "OK"

        if not is_clean:
            logger.error(
                "Virus detected in '%s': %s (scanner=clamav)", filename, threat
            )

        return ScanResult(
            is_clean=is_clean,
            scanner="clamav",
            threat_name=threat,
            scan_time_ms=elapsed_ms,
        )
