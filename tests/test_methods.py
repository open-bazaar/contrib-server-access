"""Logging in through another site, over real HTTP, with the door as the site."""

from __future__ import annotations

import re

from served import Served, client, serving
lazy import httpx


async def admin(served: Served, session: httpx.AsyncClient) -> None:
    await session.post(
        f"{served.url}/login/", data={"name": "admin", "password": served.password}
    )


async def role(served: Served, session: httpx.AsyncClient, *points: str) -> str:
    """A new role holding the points; the address of its page."""
    made = await session.post(
        f"{served.url}/ui/access/roles/",
        data={"name": "readers-" + "-".join(points), "permissions": list(points)},
    )
    assert made.status_code == 303
    return made.headers["location"]


async def through(
    served: Served, session: httpx.AsyncClient, person: str
) -> httpx.Response:
    """Set off through the door as the person, and come back."""
    sent = await session.get(f"{served.url}/login/door/?person={person}")
    while (
        sent.status_code in (302, 303, 307)
        and "/login/door/" in sent.headers["location"]
    ):
        sent = await session.get(f"{served.url}{sent.headers['location']}")
    return sent


async def test_a_first_login_takes_the_default_role_and_is_refused_without_one():
    async with serving(door=True) as served, client() as boss, client() as alice:
        refused = await through(served, alice, "alice")
        assert refused.status_code == 403
        assert "bcs_session" not in alice.cookies
        await admin(served, boss)
        readers = await role(served, boss, "stall.view")
        await boss.post(f"{served.url}{readers}/default")
        came = await through(served, alice, "alice")
        assert came.status_code == 302
        assert came.headers["location"] == "/"
        assert "no-store" in came.headers["cache-control"]
        assert (await alice.get(f"{served.url}/api/stall/me")).json() == {
            "name": "Alice"
        }
        # the default role allows the stall's own permission point
        assert (await alice.post(f"{served.url}/api/stall/echo")).status_code == 200
        listed = await boss.get(f"{served.url}/ui/access/accounts/")
        assert "Alice" in listed.text


async def test_a_login_under_way_is_taken_once_and_only_by_its_browser():
    async with (
        serving(door=True) as served,
        client() as boss,
        client() as alice,
        client() as stranger,
    ):
        await admin(served, boss)
        await boss.post(f"{served.url}{await role(served, boss, 'stall.view')}/default")
        sent = await alice.get(f"{served.url}/login/door/?person=alice")
        approved = await alice.get(f"{served.url}{sent.headers['location']}")
        callback = f"{served.url}{approved.headers['location']}"
        # another browser bringing the same answer back gets nothing
        assert (await stranger.get(callback)).status_code == 400
        assert (await alice.get(callback)).status_code == 302
        assert (await alice.get(callback)).status_code == 400
        declined = await through(served, alice, "")
        assert declined.status_code == 401


async def test_a_session_that_ran_out_is_renewed_while_the_site_still_vouches():
    async with serving(door=True) as served, client() as boss, client() as alice:
        await admin(served, boss)
        await boss.post(f"{served.url}{await role(served, boss, 'stall.view')}/default")
        await through(served, alice, "alice")
        alice.cookies.delete("bcs_session")
        renewed = await alice.get(f"{served.url}/stall")
        assert renewed.status_code == 200
        assert "bcs_session" in alice.cookies
        assert served.door is not None
        served.door.revoked.add(served.door.people["alice"])
        alice.cookies.delete("bcs_session")
        turned = await alice.get(f"{served.url}/stall")
        assert turned.status_code == 303
        assert turned.headers["location"] == "/login/"
        assert "bcs_reauth" not in alice.cookies


async def test_a_role_a_login_method_gives_stays_and_the_default_needs_a_successor():
    async with serving(door=True) as served, client() as boss:
        await admin(served, boss)
        given = await role(served, boss, "stall.view")
        other = await role(served, boss, "stall.view", "settings.roles")
        # the role's id, as the admin's own account page offers it
        account = await boss.get(f"{served.url}/ui/access/accounts/")
        mine = re.search(r'href="(/ui/access/accounts/\d+)"', account.text)
        assert mine is not None
        offered = await boss.get(f"{served.url}{mine.group(1)}")
        held = re.search(
            r'value="([^"]+)"><span><b>readers-stall\.view</b>', offered.text
        )
        assert held is not None and served.door is not None
        served.door.role = held.group(1)
        kept = await boss.post(f"{served.url}{given}/remove")
        assert kept.status_code == 422
        served.door.role = None
        await boss.post(f"{served.url}{given}/default")
        alone = await boss.post(f"{served.url}{given}/remove")
        assert alone.status_code == 422
        successor = re.search(
            r'<option value="([^"]+)">readers-stall\.view-settings\.roles</option>',
            (await boss.get(f"{served.url}{given}")).text,
        )
        assert successor is not None
        gone = await boss.post(
            f"{served.url}{given}/remove", data={"replacement": successor.group(1)}
        )
        assert gone.status_code == 303
        assert (await boss.get(f"{served.url}{given}")).status_code == 404
        assert (await boss.get(f"{served.url}{other}")).status_code == 200
