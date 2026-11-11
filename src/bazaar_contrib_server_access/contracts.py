"""What login methods and the modules sharing their targets hold server-access
to, and what it does for them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
lazy from collections.abc import Awaitable, Callable, Mapping, Sequence
lazy from contextlib import AbstractAsyncContextManager

from bazaar_core import ServiceKey
lazy from bazaar_contrib_server import Account
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


@dataclass(frozen=True, slots=True)
class Shared:
    """A kind of target its owners share with roles, such as a computer: the
    permission point sharing takes, the points a share can carry, and the
    target's name, nothing when there is no such target. A target's share
    page is /ui/access/shares/<kind>/<the target's ref>."""

    kind: str
    permission: str
    points: tuple[str, ...]
    name: Callable[[str], Awaitable[str | None]]


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
    """What server-access does for login methods, for the modules whose
    targets are owned and shared, and for those signing what their pages
    hand out."""

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

    def shared(self, shared: Shared) -> AbstractAsyncContextManager[None]:
        """Let owners share the kind's targets while open."""
        ...

    def points(
        self, kind: str, points: Sequence[str]
    ) -> AbstractAsyncContextManager[None]:
        """Let shares of the kind's targets also carry the points while open."""
        ...

    async def own(
        self, session: Session, account_id: str, kind: str, target_id: str
    ) -> None:
        """Make the account the target's owner in place of any before it, in
        the caller's transaction."""
        ...

    async def owners(
        self, session: Session, kind: str, target_ids: Sequence[str]
    ) -> Mapping[str, str]:
        """Who owns each of the targets that has an owner, in the caller's
        transaction."""
        ...

    async def forget(self, session: Session, kind: str, target_id: str) -> None:
        """Drop who owns the target and whom it is shared with, in the
        caller's transaction."""
        ...

    async def targets(
        self, account: Account, kind: str, point: str
    ) -> frozenset[str] | None:
        """The targets of the kind the account may use the point on: those it
        owns, and those shared with one of its roles for the point, as long as
        its roles hold the point; nothing when that is every target, as it is
        for admin."""
        ...

    async def can(
        self, account: Account, kind: str, target_id: str, point: str
    ) -> bool: ...

    async def can_share(self, account: Account, kind: str, target_id: str) -> bool:
        """Whether the account may share the target: admin, or the owner
        holding the kind's permission point for sharing."""
        ...

    def sign(self, label: str, value: str) -> str:
        """An HMAC-SHA256 with session.key of the label and the value, each
        percent-encoded and joined by a colon, such as an address a page
        hands out under the label image."""
        ...

    def verify(self, label: str, value: str, signature: str) -> bool:
        """Whether the signature is the value's under the label, compared in
        constant time."""
        ...


ACCESS = ServiceKey[Access]("server.access")
