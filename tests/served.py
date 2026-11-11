"""The server's entries as installed, behind server-access, with a module of
the kind feature modules are."""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
lazy import asyncio
lazy import logging
lazy import re
lazy from collections.abc import AsyncIterator, Mapping
lazy from importlib.resources import files
lazy from pathlib import Path
lazy from typing import Annotated, Any
lazy from uuid import uuid7

import httpx
from bazaar_contrib_http import HTTP
from bazaar_contrib_server import (
    SERVER,
    Account,
    PermissionItem,
    SettingsItem,
    SidebarItem,
    SidebarPanel,
    Topic,
    account,
    permitted,
)
from bazaar_contrib_server_database import SERVER_DB
from bazaar_core import Context, Contrib, ContribEntry, ContribHub, ContribSpec, load
from door import Door
from fastapi import Depends, FastAPI
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

from bazaar_contrib_server_access import ACCESS, Access, Shared

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
    # what server-access does for the modules
    access: Access
    # the test login method, when it was asked for
    door: Door | None = None


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

    async def panel(request: Request) -> Response:
        return await pages.render(request, "stall/panel.html")

    # what the stall counts, followed through the update bus
    counted = {"n": 1}

    async def count(viewer: Account, scope: object) -> dict[str, str]:
        del viewer, scope
        return {"text": str(counted["n"]), "kind": "unread"}

    async def bump(request: Request) -> Response:
        del request
        counted["n"] += 1
        return Response(status_code=204)

    async def shelf(viewer: Account, scope: Mapping[str, str]) -> dict[str, str]:
        del viewer
        return {"text": scope["shelf"]}

    async def piece(request: Request) -> Response:
        del request
        return HTMLResponse(
            '<span id="piece" data-topic="stall.count" data-tally hidden></span>'
        )

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
                    Route("/panel", panel),
                    Route("/bump", bump, methods=["POST"]),
                    Route("/piece", piece),
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
                group="server.sidebar.workbench",
                permission="stall.view",
                order=10,
                badge="stall.count",
            )
        ),
        server.topic(Topic(name="stall.count", fetch=count)),
        server.topic(Topic(name="stall.shelf", fetch=shelf, fields=("shelf",))),
        server.panel(
            SidebarPanel(
                key="stall-panel",
                src="/ui/stall/panel",
                group="server.sidebar.workbench",
                order=10,
            )
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
                src="/ui/stall/tile",
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
                        group="stall.aisles",
                        order=11 + n,
                    )
                )
            )
        yield


@asynccontextmanager
async def _stand(ctx: Context) -> AsyncIterator[None]:
    """A module whose stands are owned by whoever puts them up, and shared
    by them, as computers are."""
    server = ctx.accept(SERVER)
    access = ctx.accept(ACCESS)
    database = ctx.accept(SERVER_DB)
    names: dict[str, str] = {}

    async def name(stand_id: str) -> str | None:
        return names.get(stand_id)

    async def stand(request: Request) -> str:
        found = await server.refs.values([request.path_params["ref"]])
        assert found is not None
        return found[0]

    async def put_up(request: Request) -> Response:
        viewer: Account = request.state.account
        stand_id = str(uuid7())
        names[stand_id] = str((await request.form())["name"])
        await database.transaction(
            lambda session: access.own(session, viewer.id, "stand", stand_id)
        )
        await server.refs.load([stand_id])
        return JSONResponse({"ref": server.refs.ref(stand_id)})

    async def seen(request: Request) -> Response:
        visible = await access.targets(request.state.account, "stand", "stands.view")
        return JSONResponse(
            sorted(
                name
                for stand_id, name in names.items()
                if visible is None or stand_id in visible
            )
        )

    async def mine(request: Request) -> Response:
        viewer: Account = request.state.account
        owners = await database.read(
            lambda session: access.owners(session, "stand", list(names))
        )
        return JSONResponse(
            sorted(
                names[stand_id]
                for stand_id, owner_id in owners.items()
                if owner_id == viewer.id
            )
        )

    async def may(request: Request) -> Response:
        viewer: Account = request.state.account
        stand_id = await stand(request)
        return JSONResponse(
            {
                "delete": await access.can(viewer, "stand", stand_id, "stands.delete"),
                "share": await access.can_share(viewer, "stand", stand_id),
            }
        )

    async def paints(request: Request) -> Response:
        stand_id = await stand(request)
        return JSONResponse(
            {
                "paint": await access.can(
                    request.state.account, "stand", stand_id, "stands.paint"
                )
            }
        )

    async def take_down(request: Request) -> Response:
        stand_id = await stand(request)
        await database.transaction(
            lambda session: access.forget(session, "stand", stand_id)
        )
        del names[stand_id]
        return Response(status_code=204)

    async def sharing(request: Request) -> Response:
        # the share page in a frame, as the stand's own page would hold it
        return HTMLResponse(
            f'<iframe id="share" src="/ui/access/shares/stand/{request.path_params["ref"]}"></iframe>'
            "<script>document.getElementById('share').addEventListener('bazaar:done',"
            " () => { document.body.dataset.done = 'yes'; });</script>"
        )

    async with (
        server.module(
            "stand",
            ui=Starlette(
                routes=[
                    Route("/", seen),
                    Route("/", put_up, methods=["POST"]),
                    Route("/mine", mine),
                    Route("/{ref}/may", may),
                    Route("/{ref}/paints", paints),
                    Route("/{ref}/sharing", sharing),
                    Route("/{ref}/remove", take_down, methods=["POST"]),
                ]
            ),
        ),
        server.permission(
            PermissionItem(point="stands.view", description="stands.view")
        ),
        server.permission(
            PermissionItem(point="stands.delete", description="stands.delete")
        ),
        server.permission(
            PermissionItem(point="stands.share", description="stands.share")
        ),
        server.permission(
            PermissionItem(point="stands.paint", description="stands.paint")
        ),
        access.shared(
            Shared(
                kind="stand",
                permission="stands.share",
                points=("stands.view", "stands.delete"),
                name=name,
            )
        ),
        # another module's point that shares of stands carry as well
        access.points("stand", ("stands.paint",)),
    ):
        yield


@asynccontextmanager
async def serving(*, door: bool = False, **access: Any) -> AsyncIterator[Served]:
    """The entries running, with server-access configured as given, and the
    door as a login method when asked for."""
    found: dict[str, Any] = {}
    printed: list[str] = []

    class Printed(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            printed.append(record.getMessage())

    @asynccontextmanager
    async def look(ctx: Context) -> AsyncIterator[None]:
        found["url"] = ctx.accept(HTTP).url
        found["access"] = ctx.accept(ACCESS)
        yield

    @asynccontextmanager
    async def enter(ctx: Context) -> AsyncIterator[None]:
        server = ctx.accept(SERVER)
        pages = await server.pages("door", "door")
        locales = (
            (await asyncio.to_thread(lambda: Path(str(files("door")))))
            / "resources"
            / "locales"
        )

        async def settings(request: Request) -> Response:
            return await pages.render(request, "door/settings.html")

        found["door"] = Door(ctx.accept(ACCESS), ctx.accept(SERVER_DB))
        async with (
            server.module(
                "door",
                ui=pages.application([Route("/", settings)]),
                locales=locales,
            ),
            ctx.accept(ACCESS).method(found["door"]),
        ):
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
                    name="stand",
                    definition=Contrib(
                        accepts=[SERVER, ACCESS, SERVER_DB], lifespan=_stand
                    ),
                ),
                ContribEntry(
                    name="look",
                    definition=Contrib(accepts=[HTTP, ACCESS], lifespan=look),
                ),
                *(
                    (
                        ContribEntry(
                            name="door",
                            definition=Contrib(
                                accepts=[SERVER, ACCESS, SERVER_DB], lifespan=enter
                            ),
                        ),
                    )
                    if door
                    else ()
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
            yield Served(
                hub, found["url"], password, found["access"], found.get("door")
            )
    finally:
        logger.removeHandler(handler)


@asynccontextmanager
async def client() -> AsyncIterator[httpx.AsyncClient]:
    # building the client loads certificates from disk, which is not the loop's work
    async with await asyncio.to_thread(httpx.AsyncClient, timeout=60) as session:
        yield session
