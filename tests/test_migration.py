"""What server-access's versions make of a published database and of an empty one."""

from __future__ import annotations

lazy import asyncio
lazy from pathlib import Path

import aiosqlite
import pytest
from served import serving


async def restore(path: Path, version: int) -> None:
    fixtures = (await asyncio.to_thread(Path(__file__).resolve)).parent / "fixtures"
    dump = await asyncio.to_thread((fixtures / f"server-v{version}.sql").read_text)
    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as connection:
        await connection.executescript(dump)


async def query(path: Path, sql: str) -> list[tuple[object, ...]]:
    async with aiosqlite.connect(path) as connection, connection.execute(sql) as cursor:
        return [tuple(row) for row in await cursor.fetchall()]


async def held_by_id(path: Path) -> None:
    tables = {row[0] for row in await query(path, "SELECT name FROM sqlite_master")}
    assert "oidc_providers" not in tables
    assert "oidc_identities" not in tables
    for table in ("account_roles", "auth_settings"):
        assert not await query(
            path, f"SELECT * FROM pragma_foreign_key_list('{table}')"
        )
    columns = {row[1] for row in await query(path, "PRAGMA table_info(accounts)")}
    assert {"display_name", "avatar_url", "day_theme", "night_theme"} <= columns


@pytest.mark.parametrize("version", [3, 7])
async def test_a_published_database_keeps_its_accounts_and_roles_held_by_id(
    home: Path, version: int
):
    path = home / ".bcn" / "bcs.sqlite3"
    await restore(path, version)
    async with serving():
        pass
    await held_by_id(path)
    assert ("account", "reader") in await query(
        path, "SELECT account_id, role_id FROM account_roles"
    )
    assert ("account",) in await query(path, "SELECT id FROM accounts")
    assert ("reader",) in await query(path, "SELECT id FROM roles")


async def test_a_new_database_is_held_by_id_from_the_start(home: Path):
    async with serving():
        pass
    await held_by_id(home / ".bcn" / "bcs.sqlite3")
