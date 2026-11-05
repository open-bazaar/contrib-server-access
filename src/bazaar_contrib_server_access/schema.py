"""The accounts, roles, shares and sign-in settings, taken over from the
published history in the shape its last version left them."""

import bazaar_contrib_storage as s
from bazaar_contrib_schema import Dependency, Migration, ModuleSchema

ACCOUNTS = s.Table(
    name="accounts",
    columns=(
        s.ColumnDefinition(name="id", type="text", nullable=True),
        s.ColumnDefinition(name="name", type="text", unique=True),
        s.ColumnDefinition(name="password_hash", type="text"),
        s.ColumnDefinition(name="created_at_ms", type="integer"),
        s.ColumnDefinition(name="language", type="text", nullable=True),
        s.ColumnDefinition(name="theme", type="text", nullable=True),
        s.ColumnDefinition(name="auth_type", type="text", default="local"),
        s.ColumnDefinition(name="session_version", type="integer", default=0),
    ),
    primary_key=("id",),
)
ROLES = s.Table(
    name="roles",
    columns=(
        s.ColumnDefinition(name="id", type="text", nullable=True),
        s.ColumnDefinition(name="name", type="text", unique=True),
        s.ColumnDefinition(name="permissions", type="text"),
        s.ColumnDefinition(name="created_at_ms", type="integer"),
        s.ColumnDefinition(name="updated_at_ms", type="integer"),
    ),
    primary_key=("id",),
)
ACCOUNT_ROLES = s.Table(
    name="account_roles",
    columns=(
        s.ColumnDefinition(
            name="account_id",
            type="text",
            references=s.Reference(table="accounts", column="id", on_delete="cascade"),
        ),
        s.ColumnDefinition(
            name="role_id",
            type="text",
            references=s.Reference(table="roles", column="id", on_delete="cascade"),
        ),
    ),
    primary_key=("account_id", "role_id"),
)
AUTH_SETTINGS = s.Table(
    name="auth_settings",
    columns=(
        s.ColumnDefinition(
            name="id",
            type="integer",
            nullable=True,
            generated=True,
            check=s.Compare(
                left=s.Column(name="id"), operator="=", right=s.Value(value=1)
            ),
        ),
        s.ColumnDefinition(
            name="default_role_id",
            type="text",
            nullable=True,
            references=s.Reference(table="roles", column="id"),
        ),
        s.ColumnDefinition(name="login_order", type="text", default='["password"]'),
    ),
    primary_key=("id",),
)
OIDC_PROVIDERS = s.Table(
    name="oidc_providers",
    columns=(
        s.ColumnDefinition(name="id", type="text", nullable=True),
        s.ColumnDefinition(name="name", type="text"),
        s.ColumnDefinition(name="logo_url", type="text"),
        s.ColumnDefinition(name="issuer", type="text"),
        s.ColumnDefinition(name="client_id", type="text"),
        s.ColumnDefinition(name="client_secret", type="text"),
        s.ColumnDefinition(name="redirect_uri", type="text"),
        s.ColumnDefinition(name="created_at_ms", type="integer"),
        s.ColumnDefinition(name="updated_at_ms", type="integer"),
        s.ColumnDefinition(name="description", type="text", default=""),
        s.ColumnDefinition(
            name="default_role_id",
            type="text",
            nullable=True,
            references=s.Reference(table="roles", column="id"),
        ),
        s.ColumnDefinition(name="session_minutes", type="integer", default=10),
    ),
    primary_key=("id",),
)
OIDC_IDENTITIES = s.Table(
    name="oidc_identities",
    columns=(
        s.ColumnDefinition(name="issuer", type="text"),
        s.ColumnDefinition(name="subject", type="text"),
        s.ColumnDefinition(
            name="account_id",
            type="text",
            references=s.Reference(table="accounts", column="id", on_delete="cascade"),
        ),
        s.ColumnDefinition(
            name="provider_id",
            type="text",
            references=s.Reference(table="oidc_providers", column="id"),
        ),
        s.ColumnDefinition(name="display_name", type="text"),
        s.ColumnDefinition(name="email", type="text"),
    ),
    primary_key=("issuer", "subject"),
)
RELATIONS = s.Table(
    name="relations",
    columns=(
        s.ColumnDefinition(name="subject_id", type="text"),
        s.ColumnDefinition(name="kind", type="text"),
        s.ColumnDefinition(name="target_id", type="text"),
        s.ColumnDefinition(name="ext", type="text", nullable=True),
        s.ColumnDefinition(name="created_at_ms", type="integer"),
    ),
    primary_key=("subject_id", "kind", "target_id"),
)

BASELINE = Migration(
    version=1,
    name="access_schema",
    operations=(
        s.CreateTable(table=ACCOUNTS),
        s.CreateTable(table=ROLES),
        s.CreateTable(table=ACCOUNT_ROLES),
        s.CreateIndex(
            table="account_roles",
            index=s.Index(name="account_roles_by_role", columns=("role_id",)),
        ),
        s.CreateTable(table=AUTH_SETTINGS),
        s.CreateTable(table=OIDC_PROVIDERS),
        s.CreateTable(table=OIDC_IDENTITIES),
        s.CreateIndex(
            table="oidc_identities",
            index=s.Index(name="oidc_identities_by_account", columns=("account_id",)),
        ),
        s.CreateTable(table=RELATIONS),
        s.CreateIndex(
            table="relations",
            index=s.Index(name="relations_by_target", columns=("kind", "target_id")),
        ),
    ),
)

MODULE = ModuleSchema(
    tables=(
        "accounts",
        "roles",
        "account_roles",
        "auth_settings",
        "oidc_providers",
        "oidc_identities",
        "relations",
    ),
    migrations=(BASELINE,),
    baseline=BASELINE,
    predecessor=Dependency(package="bazaar-contrib-server-migrations", version=7),
)
