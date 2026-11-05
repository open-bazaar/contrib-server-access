"""Sessions and the login page the server's pages and APIs are behind."""

from __future__ import annotations

from contextlib import asynccontextmanager
lazy import asyncio
lazy import logging
lazy import os
lazy from collections.abc import AsyncIterator
lazy from importlib.resources import files
lazy from pathlib import Path

from bazaar_contrib_server import SERVER
from bazaar_contrib_server_database import SERVER_DB, SERVER_SCHEMA
from bazaar_contrib_server_migrations import SERVER_MIGRATIONS
from bazaar_core import Context, Contrib
from pydantic import BaseModel, ConfigDict, Field

lazy from .accounts import ADMIN, Accounts
lazy from .login import Login
lazy from .schema import MODULE
lazy from .sessions import Sessions, key

__all__ = ["AccessConfig", "access"]


class AccessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # how long a login lasts before the person is asked again
    session_minutes: int = Field(default=10, ge=1, strict=True)


@asynccontextmanager
async def _access(ctx: Context, config: AccessConfig) -> AsyncIterator[None]:
    server = ctx.accept(SERVER)
    async with ctx.accept(SERVER_SCHEMA).register(MODULE):
        home = Path(os.environ.get("BCN_HOME") or await asyncio.to_thread(Path.home))
        sessions = Sessions(await asyncio.to_thread(key, home / ".bcn" / "session.key"))
        accounts = await Accounts.open(ctx.accept(SERVER_DB))
        password = await accounts.ensure_admin()
        if password is not None:
            # the only time the password exists in the clear; it goes where
            # whoever started the server is looking
            logging.getLogger(__name__).warning(
                "created account %s with password %s; log in and change it",
                ADMIN,
                password,
            )
        resources = Path(str(files(__name__))) / "resources"
        async with (
            server.module(
                "access", static=resources / "static", locales=resources / "locales"
            ),
            server.login(
                Login(
                    await server.pages("access", __name__),
                    sessions,
                    accounts,
                    config.session_minutes,
                )
            ),
        ):
            yield


access = Contrib(
    config=AccessConfig,
    accepts=[SERVER, SERVER_DB, SERVER_SCHEMA, SERVER_MIGRATIONS],
    lifespan=_access,
)
