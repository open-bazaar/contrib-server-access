"""Sessions, the login page, accounts, roles and the login methods the
server's pages and APIs are behind."""

from __future__ import annotations

from contextlib import asynccontextmanager
lazy import asyncio
lazy import logging
lazy import os
lazy from collections.abc import AsyncIterator
lazy from importlib.resources import files
lazy from pathlib import Path

from bazaar_contrib_server import SERVER, PermissionItem, SettingsItem
from bazaar_contrib_server_database import SERVER_DB, SERVER_SCHEMA
from bazaar_contrib_server_migrations import SERVER_MIGRATIONS
from bazaar_contrib_timer import TIMER
from bazaar_core import Context, Contrib
from pydantic import BaseModel, ConfigDict, Field

from .contracts import (
    ACCESS,
    Access,
    Authorization,
    Confirmed,
    Method,
    Refused,
    Role,
    Unassigned,
    Unavailable,
)
lazy from .accounts import ADMIN, Accounts
lazy from .login import Login
lazy from .methods import Methods
lazy from .roles import Roles
lazy from .schema import MODULE
lazy from .sessions import Sessions, key
lazy from .settings import ACCOUNTS, METHODS, ROLES, Settings

__all__ = [
    "ACCESS",
    "METHODS",
    "Access",
    "AccessConfig",
    "Authorization",
    "Confirmed",
    "Method",
    "Refused",
    "Role",
    "Unassigned",
    "Unavailable",
    "access",
]


class AccessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # how long a login lasts before the person is asked again
    session_minutes: int = Field(default=10, ge=1, strict=True)


@asynccontextmanager
async def _access(ctx: Context, config: AccessConfig) -> AsyncIterator[None]:
    server = ctx.accept(SERVER)
    database = ctx.accept(SERVER_DB)
    async with ctx.accept(SERVER_SCHEMA).register(MODULE):
        home = Path(os.environ.get("BCN_HOME") or await asyncio.to_thread(Path.home))
        sessions = Sessions(await asyncio.to_thread(key, home / ".bcn" / "session.key"))
        accounts = await Accounts.open(database)
        roles = Roles(database)
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
        icons = resources / "templates" / "access" / "icons"
        lock, users, shield, door = await asyncio.to_thread(
            lambda: tuple(
                (icons / f"{name}.svg").read_text(encoding="utf-8")
                for name in ("lock", "users", "shield", "key-round")
            )
        )
        pages = await server.pages("access", __name__)
        login = Login(
            pages, sessions, accounts, roles, ctx.accept(TIMER), config.session_minutes
        )
        settings = Settings(server, pages, login, accounts, roles)
        async with (
            server.module(
                "access",
                ui=settings.app,
                static=resources / "static",
                locales=resources / "locales",
            ),
            server.login(login),
            server.permission(
                PermissionItem(point=ROLES, description="access.permission.roles")
            ),
            server.permission(
                PermissionItem(point=ACCOUNTS, description="access.permission.accounts")
            ),
            server.permission(
                PermissionItem(point=METHODS, description="access.permission.methods")
            ),
            server.settings(
                SettingsItem(
                    key="security",
                    title="access.security",
                    icon=lock,
                    group="server.settings.personal",
                    description="access.security.description",
                    src="/ui/access/security",
                    admin=True,
                )
            ),
            server.settings(
                SettingsItem(
                    key="accounts",
                    title="access.accounts",
                    icon=users,
                    group="server.settings.admin",
                    description="access.accounts.description",
                    src="/ui/access/accounts/",
                    permission=ACCOUNTS,
                )
            ),
            server.settings(
                SettingsItem(
                    key="roles",
                    title="access.roles",
                    icon=shield,
                    group="server.settings.admin",
                    description="access.roles.description",
                    src="/ui/access/roles/",
                    permission=ROLES,
                )
            ),
            server.settings(
                SettingsItem(
                    key="methods",
                    title="access.methods",
                    icon=door,
                    group="server.settings.admin",
                    description="access.methods.description",
                    src="/ui/access/methods/",
                    permission=METHODS,
                )
            ),
        ):
            ctx.offer(ACCESS, Methods(login, accounts, roles, ctx.accept(TIMER)))
            yield


access = Contrib(
    config=AccessConfig,
    accepts=[SERVER, SERVER_DB, SERVER_SCHEMA, SERVER_MIGRATIONS, TIMER],
    offers=[ACCESS],
    lifespan=_access,
)
