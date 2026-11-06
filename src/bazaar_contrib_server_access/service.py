"""ACCESS as one service: what login methods hold server-access to, and the
shares of the targets other modules own."""

from __future__ import annotations

lazy from bazaar_contrib_server import Pages, Server
lazy from bazaar_contrib_storage import Database
lazy from bazaar_contrib_timer import Timer

from .methods import Methods
from .shares import Shares
lazy from .accounts import Accounts
lazy from .login import Login
lazy from .roles import Roles


class Service(Methods, Shares):
    def __init__(
        self,
        login: Login,
        accounts: Accounts,
        roles: Roles,
        timer: Timer,
        database: Database,
        server: Server,
        pages: Pages,
    ) -> None:
        Methods.__init__(self, login, accounts, roles, timer)
        Shares.__init__(self, database, server, pages, roles)
