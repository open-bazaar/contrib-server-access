"""Roles: named sets of permission points, the accounts holding them, and the
default role people logging in through another site get at first."""

from __future__ import annotations

from dataclasses import dataclass
lazy import json
lazy from collections.abc import Sequence
lazy from typing import cast

lazy from bazaar_contrib_storage import (
    All,
    Column,
    Compare,
    Conflict,
    Database,
    Delete,
    Expression,
    In,
    Insert,
    Join,
    Record,
    Select,
    Session,
    Sort,
    Value,
)

# what a role is shared through; a role going takes its shares along
_SHARES = ("computer_share_role", "agent_share_role")
# a role's columns, read through a join
_COLUMNS: dict[str, Expression] = {
    name: Column(name=name, table="roles")
    for name in ("id", "name", "permissions", "created_at_ms", "updated_at_ms")
}


@dataclass(frozen=True, slots=True)
class StoredRole:
    id: str
    name: str
    permissions: frozenset[str]
    created_at_ms: int
    updated_at_ms: int


def _role(row: Record) -> StoredRole:
    return StoredRole(
        id=cast(str, row["id"]),
        name=cast(str, row["name"]),
        permissions=frozenset(json.loads(cast(str, row["permissions"]))),
        created_at_ms=cast(int, row["created_at_ms"]),
        updated_at_ms=cast(int, row["updated_at_ms"]),
    )


def _equals(column: str, value: str, table: str | None = None) -> Compare:
    return Compare(
        left=Column(name=column, table=table), operator="=", right=Value(value=value)
    )


class Roles:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def all(self) -> list[StoredRole]:
        rows = await self._database.read(
            lambda session: session.select(
                Select(
                    table="roles",
                    order_by=(
                        Sort(expression=Column(name="name")),
                        Sort(expression=Column(name="id")),
                    ),
                )
            )
        )
        return [_role(row) for row in rows]

    async def of(self, account_id: str) -> list[StoredRole]:
        """The roles an account holds."""
        rows = await self._database.read(
            lambda session: session.select(
                Select(
                    table="roles",
                    columns=_COLUMNS,
                    joins=(
                        Join(
                            table="account_roles",
                            on=Compare(
                                left=Column(name="role_id", table="account_roles"),
                                operator="=",
                                right=Column(name="id", table="roles"),
                            ),
                        ),
                    ),
                    where=_equals("account_id", account_id, "account_roles"),
                    order_by=(Sort(expression=Column(name="name", table="roles")),),
                )
            )
        )
        return [_role(row) for row in rows]

    async def save(self, role: StoredRole) -> None:
        await self._database.write(
            lambda session: session.insert(
                Insert(
                    table="roles",
                    rows=(
                        {
                            "id": role.id,
                            "name": role.name,
                            "permissions": json.dumps(sorted(role.permissions)),
                            "created_at_ms": role.created_at_ms,
                            "updated_at_ms": role.updated_at_ms,
                        },
                    ),
                    conflict=Conflict(
                        columns=("id",),
                        update=("name", "permissions", "updated_at_ms"),
                    ),
                )
            )
        )

    async def assign(self, account_id: str, role_ids: Sequence[str]) -> None:
        """The account holds exactly these roles from now on."""

        async def replace(session: Session) -> None:
            await session.delete(
                Delete(table="account_roles", where=_equals("account_id", account_id))
            )
            if role_ids:
                await session.insert(
                    Insert(
                        table="account_roles",
                        rows=tuple(
                            {"account_id": account_id, "role_id": role_id}
                            for role_id in dict.fromkeys(role_ids)
                        ),
                    )
                )

        await self._database.transaction(replace)

    async def default(self) -> StoredRole | None:
        rows = await self._database.read(
            lambda session: session.select(
                Select(
                    table="roles",
                    columns=_COLUMNS,
                    joins=(
                        Join(
                            table="auth_settings",
                            on=Compare(
                                left=Column(
                                    name="default_role_id", table="auth_settings"
                                ),
                                operator="=",
                                right=Column(name="id", table="roles"),
                            ),
                        ),
                    ),
                    limit=1,
                )
            )
        )
        return _role(rows[0]) if rows else None

    async def set_default(self, role_id: str) -> None:
        await self._database.write(
            lambda session: session.insert(
                Insert(
                    table="auth_settings",
                    rows=({"id": 1, "default_role_id": role_id},),
                    conflict=Conflict(columns=("id",), update=("default_role_id",)),
                )
            )
        )

    async def remove(self, role_id: str, replacement: str | None) -> None:
        """The role gone, with the accounts' hold on it and its shares; the
        replacement becomes the default role when this one was."""

        async def remove(session: Session) -> None:
            if replacement is not None:
                await session.insert(
                    Insert(
                        table="auth_settings",
                        rows=({"id": 1, "default_role_id": replacement},),
                        conflict=Conflict(columns=("id",), update=("default_role_id",)),
                    )
                )
            await session.delete(
                Delete(table="account_roles", where=_equals("role_id", role_id))
            )
            await session.delete(
                Delete(
                    table="relations",
                    where=All(
                        conditions=(
                            _equals("subject_id", role_id),
                            In(expression=Column(name="kind"), values=_SHARES),
                        )
                    ),
                )
            )
            await session.delete(Delete(table="roles", where=_equals("id", role_id)))

        await self._database.transaction(remove)
