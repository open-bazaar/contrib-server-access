"""The server's entries as installed, behind server-access, with a module of
the kind feature modules are."""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
lazy import asyncio
lazy import logging
lazy import re
lazy from collections.abc import AsyncIterator
lazy from typing import Annotated, Any

import httpx
from bazaar_contrib_http import HTTP
from bazaar_contrib_server import (
    SERVER,
    Account,
    OverviewItem,
    PermissionItem,
    SettingsItem,
    SidebarItem,
    account,
    permitted,
)
from bazaar_core import Context, Contrib, ContribEntry, ContribHub, ContribSpec, load
from fastapi import Depends, FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

ENTRIES = (
    ("timer-wheel", {}),
    ("http", {"listen": "127.0.0.1:0"}),
    ("server-database", {}),
    ("server-migrations", {}),
    ("server", {}),
    ("server-theme-night", {}),
    ("server-theme-day", {}),
)


@dataclass(frozen=True, slots=True)
class Served:
    hub: ContribHub
    url: str
    # what the admin made on this start was given, or nothing
    password: str


@asynccontextmanager
async def _stall(ctx: Context) -> AsyncIterator[None]:
    server = ctx.accept(SERVER)
    pages = await server.pages("stall", "stall")

    async def first(request: Request) -> Response:
        return await pages.render(request, "stall/first.html")

    async def second(request: Request) -> Response:
        return await pages.render(request, "stall/second.html")

    async def tile(request: Request) -> Response:
        return await pages.render(request, "stall/tile.html")

    async def echo(request: Request) -> Response:
        return JSONResponse({"size": len(await request.body())})

    async def live(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text(websocket.state.account.name)
        await websocket.close()

    api = FastAPI()

    @api.get("/me")
    async def me(viewer: Annotated[Account, Depends(account)]) -> dict[str, str]:
        return {"name": viewer.name}

    @api.post("/echo", dependencies=[Depends(permitted("stall.view"))])
    async def echoed(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    async with (
        server.module(
            "stall",
            ui=pages.application(
                [
                    Route("/", first),
                    Route("/second", second),
                    Route("/tile", tile),
                    Route("/aisle/{n}", second),
                    Route("/echo", echo, methods=["POST"]),
                    WebSocketRoute("/live", live),
                ]
            ),
            api=api,
        ),
        server.permission(PermissionItem(point="stall.view", description="stall.view")),
        server.sidebar(
            SidebarItem(
                text="stall.title",
                icon='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="9"/></svg>',
                path="/stall",
                permission="stall.view",
                order=10,
            )
        ),
        server.overview(
            OverviewItem(key="stall", title="stall.title", src="/ui/stall/tile")
        ),
        # more places than a phone's bottom bar holds
        AsyncExitStack() as aisles,
        server.settings(
            SettingsItem(
                key="stall",
                title="stall.title",
                icon='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="4"/></svg>',
                group="server.settings.personal",
                description="stall.title",
                src="/ui/stall/second",
            )
        ),
    ):
        for n in range(4):
            await aisles.enter_async_context(
                server.sidebar(
                    SidebarItem(
                        text="stall.title",
                        icon='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="5" y="5" width="14" height="14"/></svg>',
                        path=f"/stall/aisle/{n}",
                        order=11 + n,
                    )
                )
            )
        yield


@asynccontextmanager
async def serving(**access: Any) -> AsyncIterator[Served]:
    """The entries running, with server-access configured as given."""
    found: dict[str, Any] = {}
    printed: list[str] = []

    class Printed(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            printed.append(record.getMessage())

    @asynccontextmanager
    async def look(ctx: Context) -> AsyncIterator[None]:
        found["url"] = ctx.accept(HTTP).url
        yield

    composition = await asyncio.to_thread(
        load,
        [
            ContribSpec(contrib=name, config=config)
            for name, config in (*ENTRIES, ("server-access", access))
        ],
    )
    composition = composition.model_copy(
        update={
            "entries": (
                *composition.entries,
                ContribEntry(
                    name="stall", definition=Contrib(accepts=[SERVER], lifespan=_stall)
                ),
                ContribEntry(
                    name="look", definition=Contrib(accepts=[HTTP], lifespan=look)
                ),
            )
        }
    )
    logger = logging.getLogger("bazaar_contrib_server_access")
    handler = Printed()
    logger.addHandler(handler)
    try:
        async with ContribHub() as hub, hub.enable(composition):
            password = next(
                (
                    created.group(1)
                    for message in printed
                    if (created := re.search(r"with password (\S+);", message))
                ),
                "",
            )
            yield Served(hub, found["url"], password)
    finally:
        logger.removeHandler(handler)


@asynccontextmanager
async def client() -> AsyncIterator[httpx.AsyncClient]:
    # building the client loads certificates from disk, which is not the loop's work
    async with await asyncio.to_thread(httpx.AsyncClient, timeout=60) as session:
        yield session
