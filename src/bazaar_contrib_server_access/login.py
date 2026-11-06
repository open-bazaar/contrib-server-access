"""Logging in and out, who each request behind the login is from, and the
session renewed while the site an account logged in through still vouches
for it."""

from __future__ import annotations

from dataclasses import dataclass
lazy from typing import Literal, cast

lazy from bazaar_contrib_server import Admitted, Appearance, Pages
lazy from bazaar_contrib_timer import Timer, timeout
lazy from pydantic import BaseModel, ValidationError
lazy from starlette.requests import HTTPConnection, Request
lazy from starlette.responses import RedirectResponse, Response
lazy from starlette.routing import Mount, Route
lazy from starlette.types import ASGIApp, Receive, Scope, Send

lazy from .accounts import Accounts, Stored
lazy from .contracts import Confirmed, Method, Unavailable
lazy from .roles import Roles
lazy from .sessions import COOKIE, RENEWAL, RENEWAL_DAYS, Sessions

LOGIN = "/login/"
HOME = "/"
# the token tying a login under way to the browser that set off on it
BROWSER = "bcs_login"
# how long the site a login method relies on may take to answer
OUTSIDE_MS = 15_000


@dataclass(frozen=True, slots=True)
class Viewer:
    """An account as the server's pages see it."""

    id: str
    name: str
    avatar: str | None
    theme: Literal["light", "dark"] | None
    day_theme: str | None
    night_theme: str | None
    language: str | None
    admin: bool
    permissions: frozenset[str]

    def allows(self, point: str) -> bool:
        return self.admin or point in self.permissions


class _Credentials(BaseModel):
    name: str
    password: str


class Login:
    """The login module the server's pages and APIs are behind."""

    def __init__(
        self,
        pages: Pages,
        sessions: Sessions,
        accounts: Accounts,
        roles: Roles,
        timer: Timer,
        minutes: int,
    ) -> None:
        self.pages = pages
        self.sessions = sessions
        self.accounts = accounts
        self._roles = roles
        self._timer = timer
        self.minutes = minutes
        # the login methods on offer, in the order they were registered, and
        # the distribution and version each comes in
        self.methods: dict[str, Method] = {}
        self.packages: dict[str, str] = {}
        self.app: ASGIApp = pages.application(
            [
                Route("/", self._form),
                Route("/", self._login, methods=["POST"]),
                Route("/logout", self._logout, methods=["POST"]),
                Mount("/{key}", app=self._method),
            ]
        )

    async def account(self, connection: HTTPConnection) -> Admitted | Response:
        claim = self.sessions.read(connection.cookies.get(COOKIE))
        stored = None if claim is None else await self.accounts.get(claim.account_id)
        if (
            claim is not None
            and stored is not None
            and claim.session_version == stored.session_version
        ):
            return Admitted(await self._viewer(stored))
        renewed = await self._renew(connection)
        if renewed is not None:
            return renewed
        # htmx cannot follow a redirect into another page; it is told to go
        if connection.headers.get("HX-Request") == "true":
            response = Response(status_code=401, headers={"HX-Redirect": LOGIN})
        else:
            response = RedirectResponse(LOGIN, status_code=303)
        if connection.cookies.get(RENEWAL):
            response.delete_cookie(RENEWAL, path="/")
        return response

    async def dress(self, account_id: str, appearance: Appearance) -> None:
        await self.accounts.dress(account_id, appearance)

    async def page(
        self, request: Request, *, failure: str | None = None, status_code: int = 200
    ) -> Response:
        """The login page: the login methods ready to be used, and the
        account and password."""
        methods = [method for method in self.methods.values() if await method.ready()]
        return await self.pages.render(
            request,
            "access/login.html",
            status_code=status_code,
            methods=methods,
            failure=failure,
            failed=False,
        )

    def grant(
        self,
        connection: HTTPConnection,
        response: Response,
        account: Stored,
        minutes: int,
        method: str | None = None,
    ) -> None:
        """Log the account in on the response; through a login method, with
        the cookie that lets the session be renewed while it vouches."""
        secure = connection.url.scheme == "https"
        response.set_cookie(
            COOKIE,
            self.sessions.issue(account.id, account.session_version, minutes),
            max_age=minutes * 60,
            path="/",
            httponly=True,
            samesite="lax",
            # a cookie issued over https never travels over plain http
            secure=secure,
        )
        if method is None:
            response.delete_cookie(RENEWAL, path="/")
            return
        response.set_cookie(
            RENEWAL,
            self.sessions.renewal(account.id, account.session_version, method),
            max_age=RENEWAL_DAYS * 86_400,
            path="/",
            httponly=True,
            samesite="lax",
            secure=secure,
        )

    async def _viewer(self, stored: Stored) -> Viewer:
        roles = await self._roles.of(stored.id)
        return Viewer(
            id=stored.id,
            name=stored.shown,
            avatar=stored.avatar_url,
            theme=cast(Literal["light", "dark"] | None, stored.theme),
            day_theme=stored.day_theme,
            night_theme=stored.night_theme,
            language=stored.language,
            admin=stored.admin,
            permissions=frozenset(
                point for role in roles for point in role.permissions
            ),
        )

    async def _renew(self, connection: HTTPConnection) -> Admitted | None:
        """A new session for a request whose session ran out, when the login
        method the account came through still vouches for it."""
        renewal = self.sessions.renewing(connection.cookies.get(RENEWAL))
        if renewal is None:
            return None
        stored = await self.accounts.get(renewal.account_id)
        method = self.methods.get(renewal.method)
        if (
            stored is None
            or method is None
            or stored.auth_type != renewal.method
            or stored.session_version != renewal.session_version
        ):
            return None
        try:
            async with timeout(self._timer, OUTSIDE_MS):
                confirmed: Confirmed | None = await method.renew(stored.id)
        except Unavailable, TimeoutError:
            return None
        if confirmed is None or confirmed.account_id != stored.id:
            return None
        await self.accounts.known(stored.id, confirmed.name, confirmed.avatar)
        stored = await self.accounts.get(stored.id)
        if stored is None:
            return None
        # the cookies go out with whatever the request is answered with
        carrier = Response()
        self.grant(
            connection,
            carrier,
            stored,
            confirmed.minutes or self.minutes,
            renewal.method,
        )
        return Admitted(
            await self._viewer(stored),
            tuple(
                (name.decode("latin-1"), value.decode("latin-1"))
                for name, value in carrier.raw_headers
                if name == b"set-cookie"
            ),
        )

    async def _method(self, scope: Scope, receive: Receive, send: Send) -> None:
        method = self.methods.get(scope["path_params"]["key"])
        if method is None:
            await Response(status_code=404)(scope, receive, send)
            return
        await method.app(scope, receive, send)

    async def _form(self, request: Request) -> Response:
        return await self.page(request)

    async def _login(self, request: Request) -> Response:
        try:
            given = _Credentials.model_validate(dict(await request.form()))
        except ValidationError:
            given = None
        stored = (
            None
            if given is None
            else await self.accounts.verify(given.name.strip(), given.password)
        )
        if stored is None:
            # a failed login is a fragment too: htmx swaps it into the form
            return await self.pages.render(
                request, "access/login_form.html", status_code=401, failed=True
            )
        response = Response(status_code=204, headers={"HX-Redirect": HOME})
        self.grant(request, response, stored, self.minutes)
        return response

    async def _logout(self, request: Request) -> Response:
        # htmx is told where to go; a plain form is sent there
        response = (
            Response(status_code=204, headers={"HX-Redirect": LOGIN})
            if request.headers.get("HX-Request") == "true"
            else RedirectResponse(LOGIN, status_code=303)
        )
        response.delete_cookie(COOKIE, path="/")
        response.delete_cookie(RENEWAL, path="/")
        return response
