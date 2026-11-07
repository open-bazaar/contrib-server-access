"""Owning and sharing another module's targets over real HTTP, with the
stands of the test module as the targets."""

from __future__ import annotations

lazy from pathlib import Path

from served import Served, client, serving
from test_methods import admin, role, through
from test_migration import query
lazy import httpx


async def put_up(served: Served, session: httpx.AsyncClient, name: str) -> str:
    """A new stand the account owns; its ref."""
    made = await session.post(f"{served.url}/ui/stand/", data={"name": name})
    return str(made.json()["ref"])


async def seen(served: Served, session: httpx.AsyncClient) -> list[str]:
    return (await session.get(f"{served.url}/ui/stand/")).json()


async def may(
    served: Served, session: httpx.AsyncClient, stand: str
) -> dict[str, bool]:
    return (await session.get(f"{served.url}/ui/stand/{stand}/may")).json()


async def share(
    served: Served,
    session: httpx.AsyncClient,
    stand: str,
    grants: dict[str, list[str]],
) -> httpx.Response:
    """Save the stand's share page with each role given just these points;
    the role pages' addresses name the roles."""
    roles = {page: page.rsplit("/", 1)[1] for page in grants}
    return await session.post(
        f"{served.url}/ui/access/shares/stand/{stand}",
        data={
            "roles": list(roles.values()),
            "grant": [
                f"{roles[page]} {point}"
                for page, points in grants.items()
                for point in points
            ],
        },
    )


async def test_an_owner_shares_a_stand_with_a_role():
    async with (
        serving(door=True) as served,
        client() as boss,
        client() as alice,
        client() as bob,
    ):
        await admin(served, boss)
        makers = await role(
            served, boss, "stands.view", "stands.delete", "stands.share"
        )
        await boss.post(f"{served.url}{makers}/default")
        await through(served, alice, "alice")
        await through(served, bob, "bob")
        north = await put_up(served, alice, "north")
        assert await seen(served, alice) == ["north"]
        assert await may(served, alice, north) == {"delete": True, "share": True}
        # someone else's stand is not there for those it is not shared with
        assert await seen(served, bob) == []
        assert await may(served, bob, north) == {"delete": False, "share": False}
        sharing = f"{served.url}/ui/access/shares/stand/{north}"
        assert (await bob.get(sharing)).status_code == 404
        page = await alice.get(sharing)
        assert page.status_code == 200
        assert f'value="{makers.rsplit("/", 1)[1]} stands.delete"' in page.text
        saved = await share(served, alice, north, {makers: ["stands.view"]})
        assert saved.status_code == 200
        assert await seen(served, bob) == ["north"]
        # shared for viewing only, and only its owner shares it on
        assert await may(served, bob, north) == {"delete": False, "share": False}
        assert (await bob.get(sharing)).status_code == 404
        # the admin sees and may share every stand
        assert await seen(served, boss) == ["north"]
        assert (await boss.get(sharing)).status_code == 200


async def test_a_point_another_module_adds_is_shared_like_the_kinds_own():
    async with (
        serving(door=True) as served,
        client() as boss,
        client() as alice,
        client() as bob,
    ):
        await admin(served, boss)
        painters = await role(
            served, boss, "stands.view", "stands.paint", "stands.share"
        )
        await boss.post(f"{served.url}{painters}/default")
        await through(served, alice, "alice")
        await through(served, bob, "bob")
        east = await put_up(served, alice, "east")
        paints = f"{served.url}/ui/stand/{east}/paints"
        assert not (await bob.get(paints)).json()["paint"]
        page = await alice.get(f"{served.url}/ui/access/shares/stand/{east}")
        assert f'value="{painters.rsplit("/", 1)[1]} stands.paint"' in page.text
        await share(served, alice, east, {painters: ["stands.view", "stands.paint"]})
        assert (await bob.get(paints)).json()["paint"]


async def test_a_share_carries_only_what_its_owner_may_do_and_keeps_the_rest():
    async with (
        serving(door=True) as served,
        client() as boss,
        client() as carol,
        client() as bob,
    ):
        await admin(served, boss)
        viewers = await role(served, boss, "stands.view", "stands.share")
        makers = await role(served, boss, "stands.view", "stands.delete")
        await boss.post(f"{served.url}{viewers}/default")
        await through(served, carol, "carol")
        await boss.post(f"{served.url}{makers}/default")
        await through(served, bob, "bob")
        west = await put_up(served, carol, "west")
        await share(served, boss, west, {makers: ["stands.view", "stands.delete"]})
        assert await seen(served, bob) == ["west"]
        assert (await may(served, bob, west))["delete"]
        # carol may not delete stands, so she cannot share deleting either
        page = await carol.get(f"{served.url}/ui/access/shares/stand/{west}")
        made = makers.rsplit("/", 1)[1]
        assert f'value="{made} stands.view"' in page.text
        assert f'value="{made} stands.delete"' not in page.text
        refused = await share(served, carol, west, {makers: ["stands.delete"]})
        assert refused.status_code == 422
        assert (await may(served, bob, west))["delete"]
        # what she takes away goes; deleting, which she could not give, stays
        await share(served, carol, west, {makers: []})
        assert await seen(served, bob) == []
        assert (await may(served, bob, west))["delete"]


async def test_sharing_takes_its_point_and_ends_with_the_stand_or_the_role(
    home: Path,
):
    async with (
        serving(door=True) as served,
        client() as boss,
        client() as dave,
        client() as erin,
    ):
        await admin(served, boss)
        walkers = await role(served, boss, "stands.view")
        await boss.post(f"{served.url}{walkers}/default")
        await through(served, dave, "dave")
        await through(served, erin, "erin")
        east = await put_up(served, dave, "east")
        assert await seen(served, dave) == ["east"]
        # without the point for sharing, not even the owner shares
        sharing = f"{served.url}/ui/access/shares/stand/{east}"
        assert (await dave.get(sharing)).status_code == 403
        assert not (await may(served, dave, east))["share"]
        # a kind nobody shares, and a stand never put up, are not there
        assert (
            await boss.get(f"{served.url}/ui/access/shares/booth/{east}")
        ).status_code == 404
        assert (
            await boss.get(f"{served.url}/ui/access/shares/stand/999999")
        ).status_code == 404
        await share(served, boss, east, {walkers: ["stands.view"]})
        assert await seen(served, erin) == ["east"]
        others = await role(served, boss, "stands.view", "stands.delete")
        south = await put_up(served, boss, "south")
        await share(served, boss, south, {others: ["stands.view"]})
        await boss.post(f"{served.url}{others}/remove")
        await boss.post(f"{served.url}/ui/stand/{east}/remove")
        assert await seen(served, erin) == []
        assert await seen(served, dave) == []
    # the stand taken down and the role gone leave nothing behind them
    path = home / ".bcn" / "bcs.sqlite3"
    gone = [
        row[0]
        for ref in (east, others.rsplit("/", 1)[1])
        for row in await query(path, f"SELECT value FROM refs WHERE id = {ref}")
    ]
    assert len(gone) == 2
    assert not await query(
        path,
        "SELECT * FROM relations WHERE target_id = '{}' OR subject_id = '{}'".format(
            *gone
        ),
    )
