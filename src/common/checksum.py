"""Checksum + ledger: the core of idempotency and re-delivery handling."""
from __future__ import annotations
import hashlib
from pathlib import Path


def file_checksum(path: str | Path, chunk: int = 1 << 20) -> str:
    """SHA-256 of a file's bytes. Same content -> same checksum."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


class ChecksumLedger:
    """Remembers checksums we've already loaded, so re-delivered files are skipped.

    In the real pipeline, back this with a bronze metadata table instead of a set.
    """

    def __init__(self, seen: set[str] | None = None) -> None:
        self._seen: set[str] = set(seen or ())

    def is_new(self, checksum: str) -> bool:
        return checksum not in self._seen

    def record(self, checksum: str) -> None:
        self._seen.add(checksum)

    def load_if_new(self, checksum: str) -> bool:
        """Return True if this file should be loaded; False if it's a re-delivery."""
        if self.is_new(checksum):
            self.record(checksum)
            return True
        return False
