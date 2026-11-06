"""What login methods hold server-access to, and what it does for them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
lazy from collections.abc import Awaitable, Callable, Mapping, Sequence
lazy from contextlib import AbstractAsyncContextManager

from bazaar_core import ServiceKey
lazy from bazaar_contrib_storage import Session
lazy from starlette.requests import Request
lazy from starlette.responses import Response
lazy from starlette.types import ASGIApp


class Refused(Exception):
    """The login did not go through: the person declined, or what came back
    does not hold."""


class Unassigned(Refused):
    """Someone logging in for the first time has no role to be given: the
    method names none that exists, and there is no default role."""


class Unavailable(Exception):
    """The site a login method relies on could not be reached, or failed."""


@dataclass(frozen=True, slots=True)
class Authorization:
    """One login under way, from setting off to coming back; a method sends
    the challenge out and redeems what comes back with the verifier."""

    state: str
    verifier: str
    challenge: str


@dataclass(frozen=True, slots=True)
class Confirmed:
    """Whom a login method vouches for: the account, what pages call it, its
    picture, and how many minutes the session lasts, nothing for as long as
    a password login."""

    account_id: str
    name: str
    avatar: str | None = None
    minutes: int | None = None


@dataclass(frozen=True, slots=True)
class Role:
    id: str
    name: str


class Method(Protocol):
    """A way to log in through another site. Its routes are served under
    /login/<key>/, the first of them setting off; its name and description
    are text keys of its own module, its icon an SVG drawn as a square tile."""

    @property
    def key(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def icon(self) -> str: ...

    @property
    def settings(self) -> str:
        """The address of its settings page."""
        ...

    @property
    def app(self) -> ASGIApp: ...

    async def ready(self) -> bool:
        """Whether it is set up well enough to be offered on the login page."""
        ...

    async def roles(self) -> set[str]:
        """The roles it gives the people logging in for the first time."""
        ...

    async def renew(self, account_id: str) -> Confirmed | None:
        """Whether the account's authorization still holds, asked when its
        session ran out; nothing when it does not."""
        ...


class Access(Protocol):
    """What server-access does for login methods."""

    @property
    def minutes(self) -> int:
        """How long a password login lasts."""
        ...

    def method(self, method: Method) -> AbstractAsyncContextManager[None]:
        """Offer the login method while open."""
        ...

    async def start(
        self,
        request: Request,
        key: str,
        authorize: Callable[[Authorization], Awaitable[str]],
    ) -> Response:
        """Set off on a login with the method: the browser is sent where
        authorize says, or back to the login page."""
        ...

    async def finish(
        self,
        request: Request,
        key: str,
        confirm: Callable[[Authorization, Mapping[str, str]], Awaitable[Confirmed]],
    ) -> Response:
        """Come back from a login: the login under way is taken by its state
        and the account confirm vouches for is logged in."""
        ...

    async def enroll(self, session: Session, key: str, role: str | None) -> str:
        """A new account for someone logging in with the method for the
        first time, written in the method's own transaction, with its role or
        else the default role."""
        ...

    async def roles(self) -> Sequence[Role]: ...

    async def default_role(self) -> Role | None: ...


ACCESS = ServiceKey[Access]("server.access")
