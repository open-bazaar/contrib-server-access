"""The accounts that may log in, read from the server's database."""

from __future__ import annotations

from dataclasses import dataclass
lazy from time import time_ns
lazy from typing import cast
lazy from uuid import uuid7

lazy from bazaar_contrib_storage import (
    Column,
    Compare,
    Database,
    Insert,
    Record,
    Select,
    Value,
)

from .secrets import derive, hash_secret, new_secret, verify_secret

# the account made at first start; on its own, the only one there is
ADMIN = "admin"
# base64url of this many bytes: long enough that printing it once is safe
_PASSWORD_BYTES = 24


@dataclass(frozen=True, slots=True)
class Stored:
    id: str
    name: str
    password_hash: str
    language: str | None
    theme: str | None
    auth_type: str
    session_version: int

    @property
    def admin(self) -> bool:
        return self.name == ADMIN and self.auth_type == "local"


def _stored(row: Record) -> Stored:
    return Stored(
        id=cast(str, row["id"]),
        name=cast(str, row["name"]),
        password_hash=cast(str, row["password_hash"]),
        language=cast(str | None, row["language"]),
        theme=cast(str | None, row["theme"]),
        auth_type=cast(str, row["auth_type"]),
        session_version=cast(int, row["session_version"]),
    )


class Accounts:
    def __init__(self, database: Database, nobody: str) -> None:
        self._database = database
        # a hash nobody's password matches, verified for names nobody has
        self._nobody = nobody

    @classmethod
    async def open(cls, database: Database) -> Accounts:
        return cls(database, await derive(hash_secret, new_secret()))

    async def get(self, account_id: str) -> Stored | None:
        return await self._one("id", account_id)

    async def named(self, name: str) -> Stored | None:
        return await self._one("name", name)

    async def ensure_admin(self) -> str | None:
        """The password the admin was just given, when it is new; it is shown
        once and never kept in the clear."""
        if await self.named(ADMIN) is not None:
            return None
        password = new_secret(_PASSWORD_BYTES)
        password_hash = await derive(hash_secret, password)
        await self._database.write(
            lambda session: session.insert(
                Insert(
                    table="accounts",
                    rows=(
                        {
                            "id": str(uuid7()),
                            "name": ADMIN,
                            "password_hash": password_hash,
                            "created_at_ms": time_ns() // 1_000_000,
                        },
                    ),
                )
            )
        )
        return password

    async def verify(self, name: str, password: str) -> Stored | None:
        account = await self.named(name)
        # an unknown name costs the same as a wrong password, so neither can
        # be told apart by timing
        stored = (
            self._nobody
            if account is None or account.auth_type != "local"
            else account.password_hash
        )
        if not await derive(verify_secret, password, stored):
            return None
        return account

    async def _one(self, column: str, value: str) -> Stored | None:
        rows = await self._database.read(
            lambda session: session.select(
                Select(
                    table="accounts",
                    where=Compare(
                        left=Column(name=column), operator="=", right=Value(value=value)
                    ),
                    limit=1,
                )
            )
        )
        return _stored(rows[0]) if rows else None
