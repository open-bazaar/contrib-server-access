"""Who is logged in: a signed cookie that names the account, when it was
issued, the account's session version it was issued under, and when it ends."""

from __future__ import annotations

from dataclasses import dataclass
lazy import hmac
lazy import os
lazy from hashlib import sha256
lazy from pathlib import Path
lazy from tempfile import NamedTemporaryFile
lazy from time import time_ns

COOKIE = "bcs_session"
_KEY_BYTES = 32


@dataclass(frozen=True, slots=True)
class Claim:
    """What a cookie says, once its signature has been checked."""

    account_id: str
    session_version: int


class Sessions:
    """Issues and reads session cookies signed with session.key."""

    def __init__(self, key: bytes) -> None:
        self._key = key

    def issue(self, account_id: str, session_version: int, minutes: int) -> str:
        issued = time_ns() // 1_000_000
        body = f"{account_id}:{issued}:{session_version}:{issued + minutes * 60_000}"
        return f"{body}:{self._sign(body)}"

    def read(self, cookie: str | None) -> Claim | None:
        """The claim in a cookie, or nothing when it is forged or expired."""
        if not cookie:
            return None
        body, _, signature = cookie.rpartition(":")
        # as bytes, so a signature with characters a digest never has is just wrong
        if not body or not hmac.compare_digest(
            self._sign(body).encode(), signature.encode()
        ):
            return None
        parts = body.split(":")
        if len(parts) != 4:
            return None
        account_id, issued, mark, expires = parts
        if (
            not mark.isdigit()
            or not issued.isdigit()
            or not expires.isdigit()
            or time_ns() // 1_000_000 >= int(expires)
        ):
            return None
        return Claim(account_id=account_id, session_version=int(mark))

    def _sign(self, body: str) -> str:
        return hmac.new(self._key, body.encode("utf-8"), sha256).hexdigest()


def key(path: Path) -> bytes:
    """The signing key, made on first use and readable by the owner alone."""
    if path.exists():
        key = path.read_bytes()
        # a key of another size is not one of ours; signing with it would
        # fail quietly, so the start fails loudly instead
        if len(key) != _KEY_BYTES:
            raise RuntimeError(f"{path} does not hold a session key")
        return key
    key = os.urandom(_KEY_BYTES)
    path.parent.mkdir(parents=True, exist_ok=True)
    # written whole or not at all: a start cut short leaves no half a key
    # a temporary file is the owner's alone from the start
    with NamedTemporaryFile(dir=path.parent, delete=False) as staged:
        staged.write(key)
        staged.flush()
        os.fsync(staged.fileno())
    os.replace(staged.name, path)
    return key
