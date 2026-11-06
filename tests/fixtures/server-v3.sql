BEGIN TRANSACTION;
CREATE TABLE account_roles (
            account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            role_id TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
            PRIMARY KEY(account_id, role_id)
        );
INSERT INTO "account_roles" VALUES('account','reader');
CREATE TABLE accounts (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            language TEXT,
            theme TEXT
        , auth_type TEXT NOT NULL DEFAULT 'local', session_version INTEGER NOT NULL DEFAULT 0);
INSERT INTO "accounts" VALUES('account','Owner','test-only',1,NULL,NULL,'local',0);
CREATE TABLE auth_settings (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            default_role_id TEXT REFERENCES roles(id)
        );
INSERT INTO "auth_settings" VALUES(1,NULL);
CREATE TABLE computers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            secret_hash TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL
        );
INSERT INTO "computers" VALUES('computer','Workshop','test-only',1);
CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            computer_id TEXT NOT NULL REFERENCES computers (id),
            run_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            agent_id TEXT,
            event_name TEXT NOT NULL,
            thread_id TEXT,
            created_at_ms INTEGER NOT NULL,
            received_at_ms INTEGER NOT NULL,
            payload TEXT NOT NULL,
            UNIQUE (computer_id, run_id, seq)
        );
CREATE TABLE oidc_identities (
            issuer TEXT NOT NULL, subject TEXT NOT NULL,
            account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            provider_id TEXT NOT NULL REFERENCES oidc_providers(id),
            display_name TEXT NOT NULL, email TEXT NOT NULL,
            PRIMARY KEY(issuer, subject)
        );
CREATE TABLE oidc_providers (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, logo_url TEXT NOT NULL,
            issuer TEXT NOT NULL, client_id TEXT NOT NULL, client_secret TEXT NOT NULL,
            redirect_uri TEXT NOT NULL, created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL
        );
INSERT INTO "oidc_providers" VALUES('work','Work','','https://identity.example','test-client','test-only','https://app.example/callback',2,2);
CREATE TABLE oidc_transactions (
            state TEXT PRIMARY KEY,
            provider_id TEXT NOT NULL REFERENCES oidc_providers(id) ON DELETE CASCADE,
            browser_hash TEXT NOT NULL, nonce TEXT NOT NULL,
            code_verifier TEXT NOT NULL, redirect_uri TEXT NOT NULL,
            expires_at_ms INTEGER NOT NULL,
            issuer TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT ''
        );
CREATE TABLE refs (
            id INTEGER PRIMARY KEY,
            value TEXT NOT NULL UNIQUE
        );
CREATE TABLE relations (
            subject_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            target_id TEXT NOT NULL,
            ext TEXT,
            created_at_ms INTEGER NOT NULL,
            PRIMARY KEY (subject_id, kind, target_id)
        );
CREATE TABLE roles (
            id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
            permissions TEXT NOT NULL, created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL
        );
INSERT INTO "roles" VALUES('reader','Reader','["read"]',1,1);
CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            migration_name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at_ms INTEGER NOT NULL,
            duration_ms INTEGER NOT NULL
        );
INSERT INTO "schema_migrations" VALUES(1,'initial_server_schema','b28af1899bcb79c5739dfb4e07648b6a711cb7f8f55bc9259be32e08bf8fc67b',1792214656104,1);
INSERT INTO "schema_migrations" VALUES(2,'refs','45df3659796d1424456f0df86f0f8b20d8c6999f1399be790104ea1adc8782dd',1792214656107,0);
INSERT INTO "schema_migrations" VALUES(3,'roles_oidc','ab45430386d48eb19663d2504d753f620683f869c6991b5b519681652da0fa4e',1792214656111,1);
CREATE INDEX events_by_agent ON events (computer_id, agent_id, id);
CREATE INDEX events_by_name ON events (computer_id, event_name, agent_id, id);
CREATE INDEX events_by_thread ON events (computer_id, agent_id, thread_id, created_at_ms);
CREATE INDEX relations_by_target ON relations (kind, target_id);
CREATE INDEX account_roles_by_role ON account_roles(role_id);
CREATE INDEX oidc_identities_by_account ON oidc_identities(account_id);
CREATE INDEX oidc_transactions_by_expiry ON oidc_transactions(expires_at_ms);
DELETE FROM "sqlite_sequence";
COMMIT;
