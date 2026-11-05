"""Logging in and out, and who each request behind the login is from."""

from __future__ import annotations

from dataclasses import dataclass

lazy from bazaar_contrib_server import Pages
lazy from pydantic import BaseModel, ValidationError
lazy from starlette.requests import HTTPConnection, Request
lazy from starlette.responses import RedirectResponse, Response
lazy from starlette.routing import Route
lazy from starlette.types import ASGIApp

lazy from .accounts import Accounts
lazy from .sessions import COOKIE, Sessions

LOGIN = "/login/"
HOME = "/"
# the hint OIDC leaves for signing in again without being asked
REAUTH = "bcs_reauth"


@dataclass(frozen=True, slots=True)
class Viewer:
    """An account as the server's pages see it."""

    id: str
    name: str
    theme: str | None
    language: str | None
    admin: bool

    def allows(self, point: str) -> bool:
        del point
        return self.admin


class _Credentials(BaseModel):
    name: str
    password: str


class Login:
    """The login module the server's pages and APIs are behind."""

    def __init__(
        self, pages: Pages, sessions: Sessions, accounts: Accounts, minutes: int
    ) -> None:
        self._pages = pages
        self._sessions = sessions
        self._accounts = accounts
        self._minutes = minutes
        self.app: ASGIApp = pages.application(
            [
                Route("/", self._form),
                Route("/", self._login, methods=["POST"]),
                Route("/logout", self._logout, methods=["POST"]),
            ]
        )

    async def account(self, connection: HTTPConnection) -> Viewer | Response:
        claim = self._sessions.read(connection.cookies.get(COOKIE))
        stored = None if claim is None else await self._accounts.get(claim.account_id)
        if (
            claim is None
            or stored is None
            or claim.session_version != stored.session_version
        ):
            # htmx cannot follow a redirect into another page; it is told to go
            if connection.headers.get("HX-Request") == "true":
                return Response(status_code=401, headers={"HX-Redirect": LOGIN})
            return RedirectResponse(LOGIN, status_code=303)
        return Viewer(
            id=stored.id,
            name=stored.name,
            theme=stored.theme,
            language=stored.language,
            admin=stored.admin,
        )

    async def _form(self, request: Request) -> Response:
        return await self._pages.render(request, "access/login.html", failed=False)

    async def _login(self, request: Request) -> Response:
        try:
            given = _Credentials.model_validate(dict(await request.form()))
        except ValidationError:
            given = None
        stored = (
            None
            if given is None
            else await self._accounts.verify(given.name.strip(), given.password)
        )
        if stored is None:
            # a failed login is a fragment too: htmx swaps it into the form
            return await self._pages.render(
                request, "access/login_form.html", status_code=401, failed=True
            )
        response = Response(status_code=204, headers={"HX-Redirect": HOME})
        response.delete_cookie(REAUTH, path="/")
        response.set_cookie(
            COOKIE,
            self._sessions.issue(stored.id, stored.session_version, self._minutes),
            max_age=self._minutes * 60,
            path="/",
            httponly=True,
            samesite="lax",
            # a cookie issued over https never travels over plain http
            secure=request.url.scheme == "https",
        )
        return response

    async def _logout(self, request: Request) -> Response:
        del request
        response = Response(status_code=204, headers={"HX-Redirect": LOGIN})
        response.delete_cookie(COOKIE, path="/")
        response.delete_cookie(REAUTH, path="/")
        return response
