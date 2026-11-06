"""Who owns other modules' targets and which roles they share each one with,
for which points; and the page an owner shares a target on."""

from __future__ import annotations

from contextlib import asynccontextmanager
lazy import json
lazy from collections.abc import AsyncIterator
lazy from time import time_ns
lazy from typing import Annotated, cast

lazy from bazaar_contrib_server import Account, Pages, Server
lazy from bazaar_contrib_storage import (
    All,
    Column,
    Compare,
    Conflict,
    Database,
    Delete,
    In,
    Insert,
    Join,
    Predicate,
    Record,
    Select,
    Session,
)
lazy from pydantic import BaseModel, StringConstraints, ValidationError
lazy from starlette.exceptions import HTTPException
lazy from starlette.requests import Request
lazy from starlette.responses import Response
lazy from starlette.routing import Route

lazy from .contracts import Shared
lazy from .roles import Roles, equals


class _Given(BaseModel):
    # the refs of the roles on the page, and "<ref> <point>" for each point
    # checked for one of them
    roles: list[Annotated[str, StringConstraints(pattern=r"^\d{1,18}$")]]
    grant: list[
        Annotated[
            str,
            StringConstraints(pattern=r"^\d{1,18} [a-z][a-z0-9-]*\.[a-z][a-z0-9-]*$"),
        ]
    ]


def _points(row: Record) -> frozenset[str]:
    return frozenset(json.loads(cast(str, row["ext"]))["permissions"])


class Shares:
    """ACCESS: the shares' side, and the share page."""

    def __init__(
        self, database: Database, server: Server, pages: Pages, roles: Roles
    ) -> None:
        self._database = database
        self._server = server
        self._pages = pages
        self._roles = roles
        self._kinds: dict[str, Shared] = {}
        self.routes = [
            Route("/shares/{kind}/{ref}", self._page),
            Route("/shares/{kind}/{ref}", self._save, methods=["POST"]),
        ]

    @asynccontextmanager
    async def shared(self, shared: Shared) -> AsyncIterator[None]:
        if shared.kind in self._kinds:
            raise ValueError(f"targets of kind {shared.kind!r} are already shared")
        self._kinds[shared.kind] = shared
        try:
            yield
        finally:
            del self._kinds[shared.kind]

    async def own(
        self, session: Session, account_id: str, kind: str, target_id: str
    ) -> None:
        await session.insert(
            Insert(
                table="relations",
                rows=(
                    {
                        "subject_id": account_id,
                        "kind": f"{kind}_owner",
                        "target_id": target_id,
                        "ext": None,
                        "created_at_ms": time_ns() // 1_000_000,
                    },
                ),
            )
        )

    async def forget(self, session: Session, kind: str, target_id: str) -> None:
        await session.delete(
            Delete(
                table="relations",
                where=All(
                    conditions=(
                        In(
                            expression=Column(name="kind"),
                            values=(f"{kind}_owner", f"{kind}_share_role"),
                        ),
                        equals("target_id", target_id),
                    )
                ),
            )
        )

    async def targets(
        self, account: Account, kind: str, point: str
    ) -> frozenset[str] | None:
        if account.admin:
            return None
        if not account.allows(point):
            return frozenset()
        return await self._database.read(
            lambda session: self._held(session, account.id, kind, point, ()),
            snapshot=True,
        )

    async def can(
        self, account: Account, kind: str, target_id: str, point: str
    ) -> bool:
        if account.admin:
            return True
        if not account.allows(point):
            return False
        return target_id in await self._database.read(
            lambda session: self._held(
                session, account.id, kind, point, (equals("target_id", target_id),)
            ),
            snapshot=True,
        )

    async def can_share(self, account: Account, kind: str, target_id: str) -> bool:
        shared = self._kinds.get(kind)
        if shared is None or not account.allows(shared.permission):
            return False
        if account.admin:
            return True
        owners = await self._database.read(
            lambda session: session.select(
                Select(
                    table="relations",
                    where=All(
                        conditions=(
                            equals("subject_id", account.id),
                            equals("kind", f"{kind}_owner"),
                            equals("target_id", target_id),
                        )
                    ),
                    limit=1,
                )
            )
        )
        return bool(owners)

    async def _held(
        self,
        session: Session,
        account_id: str,
        kind: str,
        point: str,
        narrowed: tuple[Predicate, ...],
    ) -> frozenset[str]:
        """The targets the account owns, and those shared with one of its
        roles for the point, among those narrowed to."""
        owned = await session.select(
            Select(
                table="relations",
                columns={"target_id": Column(name="target_id")},
                where=All(
                    conditions=(
                        equals("subject_id", account_id),
                        equals("kind", f"{kind}_owner"),
                        *narrowed,
                    )
                ),
            )
        )
        found = frozenset(cast(str, row["target_id"]) for row in owned)
        shared = self._kinds.get(kind)
        if shared is None or point not in shared.points:
            return found
        given = await session.select(
            Select(
                table="relations",
                columns={
                    "target_id": Column(name="target_id", table="relations"),
                    "ext": Column(name="ext", table="relations"),
                },
                joins=(
                    Join(
                        table="account_roles",
                        on=All(
                            conditions=(
                                Compare(
                                    left=Column(name="role_id", table="account_roles"),
                                    operator="=",
                                    right=Column(name="subject_id", table="relations"),
                                ),
                                equals("account_id", account_id, "account_roles"),
                            )
                        ),
                    ),
                ),
                where=All(
                    conditions=(
                        equals("kind", f"{kind}_share_role", "relations"),
                        *narrowed,
                    )
                ),
            )
        )
        return found | {
            cast(str, row["target_id"]) for row in given if point in _points(row)
        }

    async def _target(self, request: Request) -> tuple[Shared, str, str]:
        """The kind, the target and its name a share page is about, for an
        account that may share it."""
        account: Account = request.state.account
        shared = self._kinds.get(request.path_params["kind"])
        if shared is None:
            raise HTTPException(status_code=404)
        if not account.allows(shared.permission):
            raise HTTPException(status_code=403)
        found = await self._server.refs.values([request.path_params["ref"]])
        if found is None or not await self.can_share(account, shared.kind, found[0]):
            raise HTTPException(status_code=404)
        name = await shared.name(found[0])
        if name is None:
            raise HTTPException(status_code=404)
        return shared, found[0], name

    async def _page(
        self,
        request: Request,
        *,
        chosen: dict[str, frozenset[str]] | None = None,
        saved: bool = False,
    ) -> Response:
        """The share page; what the account chose is shown again when it
        does not hold."""
        shared, target_id, name = await self._target(request)
        account: Account = request.state.account
        roles = await self._roles.all()
        await self._server.refs.load(role.id for role in roles)
        if chosen is None:
            rows = await self._database.read(
                lambda session: session.select(
                    Select(
                        table="relations",
                        where=All(
                            conditions=(
                                equals("kind", f"{shared.kind}_share_role"),
                                equals("target_id", target_id),
                            )
                        ),
                    )
                )
            )
            grants = {cast(str, row["subject_id"]): _points(row) for row in rows}
        else:
            grants = chosen
        return await self._pages.render(
            request,
            "access/shares.html",
            status_code=200 if chosen is None else 422,
            name=name,
            # only what the account itself may do can be shared
            points=[point for point in shared.points if account.allows(point)],
            roles=sorted(roles, key=lambda role: role.name),
            default=await self._roles.default(),
            grants=grants,
            invalid=chosen is not None,
            saved=saved,
        )

    async def _save(self, request: Request) -> Response:
        shared, target_id, _ = await self._target(request)
        account: Account = request.state.account
        points = frozenset(point for point in shared.points if account.allows(point))
        form = await request.form()
        try:
            given = _Given.model_validate(
                {"roles": form.getlist("roles"), "grant": form.getlist("grant")}
            )
        except ValidationError:
            return await self._page(request, chosen={})
        granted = [grant.partition(" ") for grant in given.grant]
        listed = await self._server.refs.values(given.roles)
        named = await self._server.refs.values([ref for ref, _, _ in granted])
        if listed is None or named is None:
            return await self._page(request, chosen={})
        chosen: dict[str, set[str]] = {role_id: set() for role_id in listed}
        for role_id, (_, _, point) in zip(named, granted, strict=True):
            if role_id not in chosen or point not in points:
                return await self._page(request, chosen={})
            chosen[role_id].add(point)

        async def save(session: Session) -> bool:
            known = await session.select(
                Select(
                    table="roles",
                    columns={"id": Column(name="id")},
                    where=In(expression=Column(name="id"), values=tuple(chosen)),
                )
            )
            if len(known) != len(chosen):
                return False
            rows = await session.select(
                Select(
                    table="relations",
                    where=All(
                        conditions=(
                            equals("kind", f"{shared.kind}_share_role"),
                            equals("target_id", target_id),
                            In(
                                expression=Column(name="subject_id"),
                                values=tuple(chosen),
                            ),
                        )
                    ),
                )
            )
            existing = {cast(str, row["subject_id"]): _points(row) for row in rows}
            # the points the account may not share stay as they were
            kept = {
                role_id: sorted((existing.get(role_id, frozenset()) - points) | picked)
                for role_id, picked in chosen.items()
            }
            written = {role_id: picked for role_id, picked in kept.items() if picked}
            if written:
                await session.insert(
                    Insert(
                        table="relations",
                        rows=tuple(
                            {
                                "subject_id": role_id,
                                "kind": f"{shared.kind}_share_role",
                                "target_id": target_id,
                                "ext": json.dumps({"permissions": picked}),
                                "created_at_ms": time_ns() // 1_000_000,
                            }
                            for role_id, picked in written.items()
                        ),
                        conflict=Conflict(
                            columns=("subject_id", "kind", "target_id"),
                            update=("ext",),
                        ),
                    )
                )
            if dropped := tuple(kept.keys() - written.keys()):
                await session.delete(
                    Delete(
                        table="relations",
                        where=All(
                            conditions=(
                                equals("kind", f"{shared.kind}_share_role"),
                                equals("target_id", target_id),
                                In(
                                    expression=Column(name="subject_id"),
                                    values=dropped,
                                ),
                            )
                        ),
                    )
                )
            return True

        if not chosen or await self._database.transaction(save):
            return await self._page(request, saved=True)
        return await self._page(
            request,
            chosen={role_id: frozenset(picked) for role_id, picked in chosen.items()},
        )
