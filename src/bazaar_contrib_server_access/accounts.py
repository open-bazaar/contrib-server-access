"""The accounts that may log in, read from the server's database."""

from __future__ import annotations

from dataclasses import dataclass
lazy from time import time_ns
lazy from typing import cast
lazy from uuid import uuid7

lazy from bazaar_contrib_server import Appearance
lazy from bazaar_contrib_storage import (
    All,
    Binary,
    Column,
    Compare,
    Database,
    Insert,
    Record,
    Select,
    Session,
    Sort,
    Update,
    Value,
)

from .secrets import derive, hash_secret, new_secret, verify_secret

# the account made at first start; on its own, the only one there is
ADMIN = "admin"
LOCAL = "local"
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
    display_name: str | None
    avatar_url: str | None
    day_theme: str | None
    night_theme: str | None

    @property
    def admin(self) -> bool:
        return self.name == ADMIN and self.auth_type == LOCAL

    @property
    def shown(self) -> str:
        """What pages call the account."""
        return self.display_name or self.name


def _stored(row: Record) -> Stored:
    return Stored(
        id=cast(str, row["id"]),
        name=cast(str, row["name"]),
        password_hash=cast(str, row["password_hash"]),
        language=cast(str | None, row["language"]),
        theme=cast(str | None, row["theme"]),
        auth_type=cast(str, row["auth_type"]),
        session_version=cast(int, row["session_version"]),
        display_name=cast(str | None, row["display_name"]),
        avatar_url=cast(str | None, row["avatar_url"]),
        day_theme=cast(str | None, row["day_theme"]),
        night_theme=cast(str | None, row["night_theme"]),
    )


def _id(account_id: str) -> Compare:
    return Compare(left=Column(name="id"), operator="=", right=Value(value=account_id))


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

    async def all(self) -> list[Stored]:
        """Every account, oldest first."""
        rows = await self._database.read(
            lambda session: session.select(
                Select(
                    table="accounts",
                    order_by=(Sort(expression=Column(name="created_at_ms")),),
                )
            )
        )
        return [_stored(row) for row in rows]

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
            if account is None or account.auth_type != LOCAL
            else account.password_hash
        )
        if not await derive(verify_secret, password, stored):
            return None
        return account

    async def change_password(
        self, account_id: str, password: str, *, replacing: str
    ) -> Stored | None:
        """The account under its new password, every older session refused;
        nothing when the password was changed meanwhile."""
        password_hash = await derive(hash_secret, password)

        async def replace(session: Session) -> int:
            # the hash just verified is the one replaced: a change landing in
            # between makes the password given here wrong
            changed = await session.update(
                Update(
                    table="accounts",
                    values={
                        "password_hash": Value(value=password_hash),
                        "session_version": Binary(
                            operator="+",
                            left=Column(name="session_version"),
                            right=Value(value=1),
                        ),
                    },
                    where=All(
                        conditions=(
                            _id(account_id),
                            Compare(
                                left=Column(name="password_hash"),
                                operator="=",
                                right=Value(value=replacing),
                            ),
                        )
                    ),
                )
            )
            return changed.count

        if not await self._database.transaction(replace):
            return None
        return await self.get(account_id)

    async def dress(self, account_id: str, appearance: Appearance) -> None:
        await self._database.write(
            lambda session: session.update(
                Update(
                    table="accounts",
                    values={
                        "language": Value(value=appearance.language),
                        "theme": Value(value=appearance.theme),
                        "day_theme": Value(value=appearance.day_theme),
                        "night_theme": Value(value=appearance.night_theme),
                    },
                    where=_id(account_id),
                )
            )
        )

    async def known(self, account_id: str, name: str, avatar: str | None) -> None:
        """What a login method last said the account is called and looks like."""
        await self._database.write(
            lambda session: session.update(
                Update(
                    table="accounts",
                    values={
                        "display_name": Value(value=name),
                        "avatar_url": Value(value=avatar),
                    },
                    where=_id(account_id),
                )
            )
        )

    async def enroll(self, session: Session, auth_type: str, role_id: str) -> str:
        """A new account in the caller's transaction, holding the role."""
        account_id = str(uuid7())
        await session.insert(
            Insert(
                table="accounts",
                rows=(
                    {
                        "id": account_id,
                        # as 0.2 named the accounts its identities made
                        "name": account_id,
                        "password_hash": "",
                        "created_at_ms": time_ns() // 1_000_000,
                        "auth_type": auth_type,
                    },
                ),
            )
        )
        await session.insert(
            Insert(
                table="account_roles",
                rows=({"account_id": account_id, "role_id": role_id},),
            )
        )
        return account_id

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
