"""The settings page's parts server-access brings: the admin's password, the
roles, the accounts and the login methods."""

from __future__ import annotations

lazy from collections.abc import Sequence
lazy from time import time_ns
lazy from typing import Annotated
lazy from uuid import uuid7

lazy from bazaar_contrib_server import Account, Pages, Server
lazy from pydantic import BaseModel, StringConstraints, ValidationError
lazy from starlette.exceptions import HTTPException
lazy from starlette.requests import Request
lazy from starlette.responses import RedirectResponse, Response
lazy from starlette.routing import Route

lazy from .accounts import LOCAL, Accounts
lazy from .login import Login
lazy from .roles import Roles, StoredRole

# the floor NIST SP 800-63B sets for a chosen password
MIN_PASSWORD_CHARS = 8
ROLES = "settings.roles"
ACCOUNTS = "settings.accounts"
METHODS = "settings.oidc"


class _Role(BaseModel):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
    ]
    permissions: list[str]


def _allow(request: Request, point: str) -> Account:
    account: Account = request.state.account
    if not account.allows(point):
        raise HTTPException(status_code=403)
    return account


class Settings:
    def __init__(
        self,
        server: Server,
        pages: Pages,
        login: Login,
        accounts: Accounts,
        roles: Roles,
    ) -> None:
        self._server = server
        self._pages = pages
        self._login = login
        self._accounts = accounts
        self._roles = roles
        self.routes = [
            Route("/security", self._security),
            Route("/security", self._password, methods=["POST"]),
            Route("/roles/", self._role_list),
            Route("/roles/", self._role_save, methods=["POST"]),
            Route("/roles/new", self._role_page),
            Route("/roles/{ref}", self._role_page),
            Route("/roles/{ref}", self._role_save, methods=["POST"]),
            Route("/roles/{ref}/default", self._role_default, methods=["POST"]),
            Route("/roles/{ref}/remove", self._role_remove, methods=["POST"]),
            Route("/accounts/", self._account_list),
            Route("/accounts/{ref}", self._account_page),
            Route("/accounts/{ref}", self._account_save, methods=["POST"]),
            Route("/methods/", self._methods),
        ]

    async def _security(self, request: Request) -> Response:
        if not request.state.account.admin:
            raise HTTPException(status_code=403)
        return await self._pages.render(request, "access/security.html", outcome=None)

    async def _password(self, request: Request) -> Response:
        account: Account = request.state.account
        if not account.admin:
            raise HTTPException(status_code=403)
        form = await request.form()
        current, new = str(form.get("current", "")), str(form.get("new", ""))
        if len(new) < MIN_PASSWORD_CHARS:
            return await self._pages.render(
                request, "access/security.html", status_code=422, outcome="short"
            )
        stored = await self._accounts.get(account.id)
        verified = (
            None
            if stored is None
            else await self._accounts.verify(stored.name, current)
        )
        changed = (
            None
            if verified is None
            else await self._accounts.change_password(
                account.id, new, replacing=verified.password_hash
            )
        )
        if changed is None:
            return await self._pages.render(
                request, "access/security.html", status_code=401, outcome="wrong"
            )
        response = await self._pages.render(
            request, "access/security.html", outcome="changed"
        )
        # every other session was issued under the old password; this one
        # carries on under the new
        self._login.grant(request, response, changed, self._login.minutes)
        return response

    async def _role_list(self, request: Request) -> Response:
        _allow(request, ROLES)
        roles = await self._roles.all()
        await self._server.refs.load(role.id for role in roles)
        return await self._pages.render(
            request,
            "access/roles.html",
            roles=roles,
            default=await self._roles.default(),
        )

    async def _role_page(
        self, request: Request, *, error: str | None = None, status_code: int = 200
    ) -> Response:
        _allow(request, ROLES)
        role = await self._found(request)
        roles = await self._roles.all()
        await self._server.refs.load(other.id for other in roles)
        # points read as module.action, grouped by their module
        groups: dict[str, list[str]] = {}
        for item in self._server.permissions:
            groups.setdefault(item.point.partition(".")[0], []).append(item.point)
        return await self._pages.render(
            request,
            "access/role.html",
            status_code=status_code,
            role=role,
            roles=roles,
            groups=groups,
            descriptions={
                item.point: item.description for item in self._server.permissions
            },
            default=await self._roles.default(),
            error=error,
        )

    async def _role_save(self, request: Request) -> Response:
        _allow(request, ROLES)
        role = await self._found(request)
        form = await request.form()
        try:
            given = _Role.model_validate(
                {"name": form.get("name"), "permissions": form.getlist("permissions")}
            )
        except ValidationError:
            return await self._role_page(request, error="invalid", status_code=422)
        if any(
            other.name == given.name and (role is None or other.id != role.id)
            for other in await self._roles.all()
        ):
            return await self._role_page(request, error="duplicate", status_code=422)
        registered = {item.point for item in self._server.permissions}
        now = time_ns() // 1_000_000
        saved = StoredRole(
            id=str(uuid7()) if role is None else role.id,
            name=given.name,
            # what no module registers right now stays on the role
            permissions=(frozenset() if role is None else role.permissions - registered)
            | (frozenset(given.permissions) & registered),
            created_at_ms=now if role is None else role.created_at_ms,
            updated_at_ms=now,
        )
        await self._roles.save(saved)
        await self._server.refs.load([saved.id])
        return RedirectResponse(
            f"/ui/access/roles/{self._server.refs.ref(saved.id)}", status_code=303
        )

    async def _role_default(self, request: Request) -> Response:
        _allow(request, ROLES)
        role = await self._found(request)
        if role is None:
            raise HTTPException(status_code=404)
        await self._roles.set_default(role.id)
        return RedirectResponse(
            f"/ui/access/roles/{request.path_params['ref']}", status_code=303
        )

    async def _role_remove(self, request: Request) -> Response:
        _allow(request, ROLES)
        role = await self._found(request)
        if role is None:
            raise HTTPException(status_code=404)
        replacement = str((await request.form()).get("replacement", "")) or None
        default = await self._roles.default()
        if default is not None and default.id == role.id:
            others = {
                other.id for other in await self._roles.all() if other.id != role.id
            }
            if replacement not in others:
                return await self._role_page(
                    request, error="replacement", status_code=422
                )
        else:
            replacement = None
        for method in self._login.methods.values():
            if role.id in await method.roles():
                return await self._role_page(request, error="method", status_code=422)
        await self._roles.remove(role.id, replacement)
        return RedirectResponse("/ui/access/roles/", status_code=303)

    async def _account_list(self, request: Request) -> Response:
        _allow(request, ACCOUNTS)
        accounts = await self._accounts.all()
        await self._server.refs.load(account.id for account in accounts)
        return await self._pages.render(
            request,
            "access/accounts.html",
            accounts=accounts,
            methods=self._login.methods,
            local=LOCAL,
        )

    async def _account_page(self, request: Request) -> Response:
        _allow(request, ACCOUNTS)
        values = await self._server.refs.values([request.path_params["ref"]])
        account = None if values is None else await self._accounts.get(values[0])
        if account is None:
            raise HTTPException(status_code=404)
        return await self._pages.render(
            request,
            "access/account.html",
            shown=account,
            methods=self._login.methods,
            local=LOCAL,
            roles=await self._roles.all(),
            held={role.id for role in await self._roles.of(account.id)},
        )

    async def _account_save(self, request: Request) -> Response:
        _allow(request, ACCOUNTS)
        values = await self._server.refs.values([request.path_params["ref"]])
        account = None if values is None else await self._accounts.get(values[0])
        if account is None:
            raise HTTPException(status_code=404)
        chosen: Sequence[str] = [
            str(value) for value in (await request.form()).getlist("roles")
        ]
        known = {role.id for role in await self._roles.all()}
        if not set(chosen) <= known:
            raise HTTPException(status_code=422)
        await self._roles.assign(account.id, chosen)
        return RedirectResponse(
            f"/ui/access/accounts/{request.path_params['ref']}", status_code=303
        )

    async def _methods(self, request: Request) -> Response:
        _allow(request, METHODS)
        return await self._pages.render(
            request,
            "access/methods.html",
            methods=[
                (method, await method.ready())
                for method in self._login.methods.values()
            ],
            packages=self._login.packages,
            default=await self._roles.default(),
        )

    async def _found(self, request: Request) -> StoredRole | None:
        """The role a path names, nothing for a new one; a name that leads
        nowhere is no page at all."""
        short = request.path_params.get("ref")
        if short is None:
            return None
        values = await self._server.refs.values([short])
        role = (
            None
            if values is None
            else next(
                (role for role in await self._roles.all() if role.id == values[0]),
                None,
            )
        )
        if role is None:
            raise HTTPException(status_code=404)
        return role
