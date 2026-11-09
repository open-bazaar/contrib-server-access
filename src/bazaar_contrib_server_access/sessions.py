"""Who is logged in: a signed cookie that names the account, when it was
issued, the account's session version it was issued under, and when it ends;
and, after a login through another site, a longer one that lets the session
be renewed while that site still vouches for the account."""

from __future__ import annotations

from dataclasses import dataclass
lazy import hmac
lazy import os
lazy from hashlib import sha256
lazy from pathlib import Path
lazy from tempfile import NamedTemporaryFile
lazy from time import time_ns
lazy from urllib.parse import quote

COOKIE = "bcs_session"
RENEWAL = "bcs_reauth"
RENEWAL_DAYS = 30
_KEY_BYTES = 32


@dataclass(frozen=True, slots=True)
class Claim:
    """What a cookie says, once its signature has been checked."""

    account_id: str
    session_version: int


@dataclass(frozen=True, slots=True)
class Renewal:
    """What a renewal cookie says: whose session, under which version, and
    the login method that vouches for it."""

    account_id: str
    session_version: int
    method: str


class Sessions:
    """Issues and reads session cookies signed with session.key, and signs
    other values with it under their labels."""

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

    def renewal(self, account_id: str, session_version: int, method: str) -> str:
        ends = time_ns() // 1_000_000 + RENEWAL_DAYS * 86_400_000
        body = f"{account_id}:{session_version}:{method}:{ends}"
        return f"{body}:{self.sign('renewal', body)}"

    def renewing(self, cookie: str | None) -> Renewal | None:
        """The renewal a cookie asks for, or nothing when it is forged or
        expired."""
        if not cookie:
            return None
        body, _, signature = cookie.rpartition(":")
        if not body or not self.verify("renewal", body, signature):
            return None
        parts = body.split(":")
        if len(parts) != 4:
            return None
        account_id, mark, method, ends = parts
        if (
            not mark.isdigit()
            or not ends.isdigit()
            or time_ns() // 1_000_000 >= int(ends)
        ):
            return None
        return Renewal(account_id, int(mark), method)

    def sign(self, label: str, value: str) -> str:
        """The value signed with the session key under the label, both
        percent-encoded before they are joined, so no other label and value
        give the same signature."""
        return self._sign(f"{quote(label, safe='')}:{quote(value, safe='')}")

    def verify(self, label: str, value: str, signature: str) -> bool:
        # as bytes, so a signature with characters a digest never has is just wrong
        return hmac.compare_digest(self.sign(label, value).encode(), signature.encode())

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
