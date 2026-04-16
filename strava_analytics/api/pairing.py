"""Short-lived pairing codes for bootstrapping a mobile client's API key.

The desktop/web user opens Settings, clicks "Pair mobile app", and gets a
QR + a short code. The mobile app scans the QR or types the code, calls
``POST /api/auth/pair/claim`` once, and receives the API key + base URL
to use for every subsequent request. Codes are single-use and expire
after ``TTL_SECONDS`` — a scanned-but-not-claimed code can be reissued
safely.

Storage is in-process only. A process restart invalidates outstanding
codes, which is correct: a pair code that outlives the session could
leak keys on server replacement.
"""

from __future__ import annotations

import secrets
import string
import threading
import time
from dataclasses import dataclass


TTL_SECONDS = 10 * 60  # 10 minutes — long enough to scan + type, short enough to be safe.
# Short alphabet: digits + uppercase without 0/O/1/I/L to avoid misreads.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LEN = 8


@dataclass
class _PairRecord:
    api_key: str
    api_base: str
    expires_at: float


_store: dict[str, _PairRecord] = {}
_lock = threading.Lock()


def _gc() -> None:
    """Drop expired entries. Called on every create/claim."""
    now = time.time()
    expired = [k for k, v in _store.items() if v.expires_at <= now]
    for k in expired:
        _store.pop(k, None)


def generate_code() -> str:
    """Return a fresh random pairing code."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LEN))


def create_pair(api_key: str, api_base: str) -> tuple[str, float]:
    """Register a new pair code. Returns ``(code, expires_at_unix)``."""
    with _lock:
        _gc()
        code = generate_code()
        # Collision-avoid — vanishingly unlikely at 8 chars of 31-alphabet
        # but deterministic.
        while code in _store:
            code = generate_code()
        expires_at = time.time() + TTL_SECONDS
        _store[code] = _PairRecord(
            api_key=api_key, api_base=api_base, expires_at=expires_at
        )
        return code, expires_at


def claim(code: str) -> _PairRecord | None:
    """Consume a pair code. Returns ``None`` if missing or expired."""
    with _lock:
        _gc()
        record = _store.pop(code, None)
        if record is None:
            return None
        if record.expires_at <= time.time():
            return None
        return record


def peek(code: str) -> _PairRecord | None:
    """Look up without consuming — used by tests only."""
    with _lock:
        _gc()
        return _store.get(code)
