"""Encryption-at-rest for the `api_settings` blob.

`AppSettings.api_settings` holds the third-party LLM/embedding API keys.
A DB compromise must not hand over the keys, so the column is wrapped in
`EncryptedJSONB`: the dict is JSON-serialised, Fernet-encrypted, and
stored as a `{"_enc": "<token>"}` envelope in the same JSONB column.

Transparent: every reader of `api_settings` keeps getting a plain dict
and every writer keeps assigning a plain dict — encrypt on bind, decrypt
on result, no call-site changes, no column-type migration.

Key source: `ENCRYPTION_KEY` (a urlsafe-base64 Fernet key). Generate:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Dev (no key set): pass-through plaintext so local work needs no config.
Production: `config._guard_production` refuses to boot without the key.
Backward-compatible: rows written before this (no `_enc` envelope) are
returned as-is, so existing plaintext settings keep working until the
user next saves them (which re-stores them encrypted).
"""

import json

from cryptography.fernet import Fernet
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator

from app.config import settings

_ENVELOPE = "_enc"


def _fernet() -> Fernet | None:
    # Read the key at call time (not import) so tests can toggle it.
    key = (settings.encryption_key or "").strip()
    return Fernet(key.encode()) if key else None


def encrypt_settings(data: dict) -> dict:
    f = _fernet()
    if f is None:
        return data  # dev: no key configured → store plaintext
    token = f.encrypt(json.dumps(data, ensure_ascii=False).encode()).decode()
    return {_ENVELOPE: token}


def decrypt_settings(stored: dict | None) -> dict:
    if not stored:
        return {}
    if _ENVELOPE not in stored:
        return stored  # legacy plaintext row — backward compatible
    f = _fernet()
    if f is None:
        raise RuntimeError(
            "api_settings is encrypted but ENCRYPTION_KEY is not set"
        )
    return json.loads(f.decrypt(stored[_ENVELOPE].encode()).decode())


class EncryptedJSONB(TypeDecorator):
    """JSONB column whose dict value is encrypted at rest."""

    impl = JSONB
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_settings(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return decrypt_settings(value)
