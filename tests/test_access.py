"""Logging in and out, and what a request without a session gets, over real HTTP."""

from __future__ import annotations

import pytest
from served import client, serving
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus
from websockets.typing import Origin

TOO_LARGE = b"x" * (1024 * 1024 + 1)


class stays(connect):
    """A WebSocket client that reports a redirect instead of following it."""

    def process_redirect(self, exc: Exception) -> Exception | str:
        return exc


async def test_the_admin_made_at_first_start_logs_in_and_out():
    async with serving() as served, client() as session:
        assert served.password
        page = await session.get(f"{served.url}/login/")
        assert page.status_code == 200
        assert 'name="password"' in page.text
        assert "frame-ancestors 'self'" in page.headers["content-security-policy"]
        wrong = await session.post(
            f"{served.url}/login/", data={"name": "admin", "password": "not it"}
        )
        assert wrong.status_code == 401
        assert "bcs_session" not in session.cookies
        login = await session.post(
            f"{served.url}/login/", data={"name": "admin", "password": served.password}
        )
        assert login.status_code == 204
        assert login.headers["hx-redirect"] == "/"
        overview = await session.get(f"{served.url}/overview")
        assert overview.status_code == 200
        assert "no-store" in overview.headers["cache-control"]
        assert "frame-ancestors 'self'" in overview.headers["content-security-policy"]
        assert (await session.get(f"{served.url}/api/stall/me")).json() == {
            "name": "admin"
        }
        logout = await session.post(f"{served.url}/login/logout")
        assert logout.status_code == 204
        assert logout.headers["hx-redirect"] == "/login/"
        assert (await session.get(f"{served.url}/overview")).status_code == 303


async def test_requests_without_a_session_go_to_the_login_page():
    async with serving() as served, client() as session:
        for path in ("/overview", "/stall/second", "/ui/stall/", "/api/stall/me"):
            sent = await session.get(f"{served.url}{path}")
            assert sent.status_code == 303, path
            assert sent.headers["location"] == "/login/"
        told = await session.get(
            f"{served.url}/ui/stall/second", headers={"HX-Request": "true"}
        )
        assert told.status_code == 401
        assert told.headers["hx-redirect"] == "/login/"
        for cookie in (
            b"bcs_session=admin:0:0:0:forged",
            "bcs_session=admin:0:0:0:é".encode("latin-1"),
        ):
            forged = await session.get(
                f"{served.url}/overview", headers={b"Cookie": cookie}
            )
            assert forged.status_code == 303, cookie


async def test_oversized_bodies_and_cross_site_writes_are_refused():
    async with serving() as served, client() as session:
        await session.post(
            f"{served.url}/login/", data={"name": "admin", "password": served.password}
        )
        same = {"Sec-Fetch-Site": "same-origin"}
        written = await session.post(
            f"{served.url}/api/stall/echo", content=b"goods", headers=same
        )
        assert written.status_code == 200
        assert written.json() == {"size": 5}
        for path in ("/api/stall/echo", "/ui/stall/echo"):
            refused = await session.post(
                f"{served.url}{path}", content=TOO_LARGE, headers=same
            )
            assert refused.status_code == 413, path
        for headers in (
            {"Sec-Fetch-Site": "cross-site"},
            {"Origin": "http://elsewhere.example"},
        ):
            crossed = await session.post(
                f"{served.url}/api/stall/echo", content=b"goods", headers=headers
            )
            assert crossed.status_code == 403, headers


async def test_a_login_lasts_the_configured_minutes():
    async with serving(session_minutes=25) as served, client() as session:
        login = await session.post(
            f"{served.url}/login/", data={"name": "admin", "password": served.password}
        )
        cookie = login.headers["set-cookie"].lower()
        assert "max-age=1500" in cookie
        assert "httponly" in cookie
        assert "samesite=lax" in cookie


async def test_a_websocket_behind_the_login_needs_a_session_from_this_site():
    async with serving() as served, client() as session:
        address = f"ws{served.url.removeprefix('http')}/ui/stall/live"
        with pytest.raises(InvalidStatus) as anonymous:
            async with stays(address):
                pass
        assert anonymous.value.response.status_code == 303
        assert anonymous.value.response.headers["Location"] == "/login/"
        await session.post(
            f"{served.url}/login/", data={"name": "admin", "password": served.password}
        )
        cookie = {"Cookie": f"bcs_session={session.cookies['bcs_session']}"}
        async with connect(
            address, additional_headers=cookie, origin=Origin(served.url)
        ) as live:
            assert await live.recv() == "admin"
        with pytest.raises(InvalidStatus) as crossed:
            async with connect(
                address,
                additional_headers=cookie,
                origin=Origin("http://elsewhere.example"),
            ):
                pass
        assert crossed.value.response.status_code == 403
