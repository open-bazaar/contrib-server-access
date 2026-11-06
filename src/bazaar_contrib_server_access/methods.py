"""What server-access does for login methods: their place under /login, the
logins under way in memory, the accounts they make, and the roles they
give."""

from __future__ import annotations

import re
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
lazy import asyncio
lazy import base64
lazy import hashlib
lazy from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
lazy from importlib.metadata import packages_distributions, version
lazy from secrets import token_urlsafe
lazy from typing import cast
lazy from urllib.parse import urlsplit

lazy from bazaar_contrib_storage import Column, Compare, Select, Session, Value
lazy from bazaar_contrib_timer import Timer, timeout
lazy from pydantic import BaseModel, Field, ValidationError, field_validator
lazy from starlette.requests import Request
lazy from starlette.responses import RedirectResponse, Response

lazy from .accounts import Accounts
lazy from .contracts import (
    Authorization,
    Confirmed,
    Method,
    Refused,
    Role,
    Unassigned,
    Unavailable,
)
lazy from .login import BROWSER, HOME, OUTSIDE_MS, Login
lazy from .roles import Roles

# a method's key is one segment of an address
KEY = r"^[a-z][a-z0-9-]*$"
# a login under way is kept this long, and only so many of them at once
LIFETIME_MS = 600_000
MAX_PENDING = 1024
# the routes of server-access itself, beside the methods' own
_TAKEN = frozenset({"logout"})
# what a login answers with: kept by nobody, sent nowhere along
_PRIVATE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


@dataclass(frozen=True, slots=True)
class _Pending:
    method: str
    authorization: Authorization
    # the browser's token, as a digest: the cookie itself is the browser's alone
    browser: str
    back: str
    ends_ms: int


class _Back(BaseModel):
    return_to: str = Field(default=HOME, max_length=8192)

    @field_validator("return_to")
    @classmethod
    def local(cls, value: str) -> str:
        parts = urlsplit(value)
        if (
            parts.scheme
            or parts.netloc
            or not value.startswith("/")
            or value.startswith("//")
            or "\\" in value
        ):
            raise ValueError("return_to is a path on this site")
        return value


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _package(method: Method) -> str:
    """The distribution a method came in, with its version, as the login
    methods page names it."""
    names = packages_distributions().get(type(method).__module__.partition(".")[0])
    return f"{names[0]} {version(names[0])}" if names else ""


class Methods:
    """ACCESS: the login methods' side of the login."""

    def __init__(
        self, login: Login, accounts: Accounts, roles: Roles, timer: Timer
    ) -> None:
        self._login = login
        self._accounts = accounts
        self._roles = roles
        self._timer = timer
        self._pending: OrderedDict[str, _Pending] = OrderedDict()

    @property
    def minutes(self) -> int:
        return self._login.minutes

    @asynccontextmanager
    async def method(self, method: Method) -> AsyncIterator[None]:
        if not re.fullmatch(KEY, method.key) or method.key in _TAKEN:
            raise ValueError(f"{method.key!r} cannot name a login method")
        if method.key in self._login.methods:
            raise ValueError(f"login method {method.key!r} is already registered")
        self._login.methods[method.key] = method
        self._login.packages[method.key] = await asyncio.to_thread(_package, method)
        try:
            yield
        finally:
            del self._login.methods[method.key]
            del self._login.packages[method.key]

    async def start(
        self,
        request: Request,
        key: str,
        authorize: Callable[[Authorization], Awaitable[str]],
    ) -> Response:
        try:
            back = _Back.model_validate(dict(request.query_params)).return_to
        except ValidationError:
            back = HOME
        verifier = token_urlsafe(32)
        authorization = Authorization(
            state=token_urlsafe(32),
            verifier=verifier,
            challenge=base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode("ascii")).digest()
            )
            .rstrip(b"=")
            .decode("ascii"),
        )
        try:
            async with timeout(self._timer, OUTSIDE_MS):
                address = await authorize(authorization)
        except Unavailable, TimeoutError:
            return await self._failed(request, "unavailable", 503)
        browser = token_urlsafe(32)
        now = self._timer.now_ms
        self._pending[authorization.state] = _Pending(
            key, authorization, _digest(browser), back, now + LIFETIME_MS
        )
        # only read when taken, so the oldest is also the least recently used
        while self._pending and (
            len(self._pending) > MAX_PENDING
            or next(iter(self._pending.values())).ends_ms <= now
        ):
            self._pending.popitem(last=False)
        response = RedirectResponse(address, status_code=302, headers=_PRIVATE)
        response.set_cookie(
            BROWSER,
            browser,
            max_age=LIFETIME_MS // 1000,
            path="/login",
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
        return response

    async def finish(
        self,
        request: Request,
        key: str,
        confirm: Callable[[Authorization, Mapping[str, str]], Awaitable[Confirmed]],
    ) -> Response:
        state = request.query_params.get("state", "")
        pending = self._pending.get(state)
        if (
            pending is None
            or pending.method != key
            or pending.ends_ms <= self._timer.now_ms
            or pending.browser != _digest(request.cookies.get(BROWSER, ""))
        ):
            return await self._failed(request, "expired", 400)
        del self._pending[state]
        try:
            async with timeout(self._timer, OUTSIDE_MS):
                confirmed = await confirm(pending.authorization, request.query_params)
        except Unassigned:
            return await self._failed(request, "unassigned", 403)
        except Refused:
            return await self._failed(request, "refused", 401)
        except Unavailable, TimeoutError:
            return await self._failed(request, "unavailable", 503)
        await self._accounts.known(
            confirmed.account_id, confirmed.name, confirmed.avatar
        )
        account = await self._accounts.get(confirmed.account_id)
        if account is None:
            return await self._failed(request, "refused", 401)
        response = RedirectResponse(pending.back, status_code=302, headers=_PRIVATE)
        response.delete_cookie(BROWSER, path="/login")
        self._login.grant(
            request, response, account, confirmed.minutes or self.minutes, key
        )
        return response

    async def enroll(self, session: Session, key: str, role: str | None) -> str:
        chosen = (
            await session.select(
                Select(
                    table="roles",
                    where=Compare(
                        left=Column(name="id"), operator="=", right=Value(value=role)
                    ),
                    limit=1,
                )
            )
            if role is not None
            else ()
        )
        if chosen:
            return await self._accounts.enroll(session, key, cast(str, chosen[0]["id"]))
        default = await session.select(
            Select(
                table="auth_settings",
                where=Compare(
                    left=Column(name="id"), operator="=", right=Value(value=1)
                ),
            )
        )
        role_id = cast(str | None, default[0]["default_role_id"]) if default else None
        if role_id is None:
            raise Unassigned
        return await self._accounts.enroll(session, key, role_id)

    async def roles(self) -> Sequence[Role]:
        return [Role(role.id, role.name) for role in await self._roles.all()]

    async def default_role(self) -> Role | None:
        role = await self._roles.default()
        return None if role is None else Role(role.id, role.name)

    async def _failed(
        self, request: Request, reason: str, status_code: int
    ) -> Response:
        response = await self._login.page(
            request, failure=f"access.login.{reason}", status_code=status_code
        )
        response.headers.update(_PRIVATE)
        response.delete_cookie(BROWSER, path="/login")
        return response
