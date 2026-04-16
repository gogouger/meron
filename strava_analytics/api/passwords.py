"""Password hashing helpers.

Wraps ``werkzeug.security`` so we don't take a dependency on passlib or
bcrypt-cffi — werkzeug is already pulled in transitively by Flask.
Default hash is scrypt (moderate cost), which is fine for a self-hosted
app with a small user base.
"""

from __future__ import annotations

from werkzeug.security import check_password_hash, generate_password_hash


_HASH_METHOD = "scrypt:32768:8:1"


def hash_password(password: str) -> str:
    """Return a salted hash safe to store in the DB."""
    if not password:
        raise ValueError("password must not be empty")
    return generate_password_hash(password, method=_HASH_METHOD)


def verify_password(password: str, hashed: str | None) -> bool:
    """Constant-time compare ``password`` to a stored hash."""
    if not hashed:
        return False
    try:
        return check_password_hash(hashed, password or "")
    except Exception:
        return False
