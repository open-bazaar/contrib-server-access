# bazaar-contrib-server-access

Logging in to the Bazaar Compute server: the login page, sessions, accounts and roles. On its first start it creates the `admin` account and writes its password to the log once.

```toml
[[contribs]]
package = "bazaar-contrib-server-access~=0.3.0rc2"
[[contribs.enabled]]
entry = "server-access"
[contribs.enabled.config]
session_minutes = 10
```

`session_minutes` is how long a login lasts before the person is asked again. Other ways to log in come from contribs that accept `ACCESS`, such as `bazaar-contrib-server-github`.
