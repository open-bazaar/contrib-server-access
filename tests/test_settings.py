"""The settings parts server-access brings, behind their permission points, over real HTTP."""

from __future__ import annotations

import re

from served import client, serving
from test_methods import admin, role, through


async def test_settings_parts_and_pages_follow_the_permission_points():
    async with serving(door=True) as served, client() as boss, client() as alice:
        await admin(served, boss)
        await boss.post(f"{served.url}{await role(served, boss, 'stall.view')}/default")
        managers = await role(served, boss, "settings.roles")
        await through(served, alice, "alice")
        directory = await alice.get(f"{served.url}/ui/settings/")
        assert "/ui/settings/appearance" in directory.text
        assert "/ui/settings/roles" not in directory.text
        assert "/ui/settings/security" not in directory.text
        assert (await alice.get(f"{served.url}/ui/access/roles/")).status_code == 403
        assert (await alice.get(f"{served.url}/ui/access/security")).status_code == 403
        # the admin gives alice the managers' role too
        listed = await boss.get(f"{served.url}/ui/access/accounts/")
        page = next(
            href
            for href, name in re.findall(
                r'href="(/ui/access/accounts/\d+)">.*?<b>([^<]+)</b>', listed.text
            )
            if name == "Alice"
        )
        offered = await boss.get(f"{served.url}{page}")
        ids = re.findall(r'name="roles" value="([^"]+)"', offered.text)
        assert len(ids) == 2
        assert (
            await boss.post(f"{served.url}{page}", data={"roles": ids})
        ).status_code == 303
        assert (await alice.get(f"{served.url}/ui/access/roles/")).status_code == 200
        assert (
            "/ui/settings/roles" in (await alice.get(f"{served.url}/ui/settings/")).text
        )
        assert (await alice.get(f"{served.url}{managers}")).status_code == 200


async def test_the_admin_changes_its_password_and_its_other_sessions_end():
    async with serving() as served, client() as here, client() as there:
        await admin(served, here)
        await admin(served, there)
        security = f"{served.url}/ui/access/security"
        short = await here.post(
            security, data={"current": served.password, "new": "short"}
        )
        assert short.status_code == 422
        wrong = await here.post(
            security, data={"current": "not it", "new": "a longer one"}
        )
        assert wrong.status_code == 401
        changed = await here.post(
            security, data={"current": served.password, "new": "a longer one"}
        )
        assert changed.status_code == 200
        assert (await here.get(f"{served.url}/stall")).status_code == 200
        assert (await there.get(f"{served.url}/stall")).status_code == 303
        again = await there.post(
            f"{served.url}/login/", data={"name": "admin", "password": "a longer one"}
        )
        assert again.status_code == 204
