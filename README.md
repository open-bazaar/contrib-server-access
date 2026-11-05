# bazaar-contrib-server-access

Sessions and the login page the Bazaar Compute server is behind. The `server-access` entry registers itself with the server as its login module: the login page at `/login/`, signed `bcs_session` cookies, and the account each request behind the login is from. On its first start it creates the `admin` account and writes its password to the log once.

```toml
[[contribs]]
package = "bazaar-contrib-server-access~=0.3.0rc1"
[[contribs.enabled]]
entry = "server-access"
[contribs.enabled.config]
session_minutes = 10
```

`session_minutes` is how long a login lasts before the person is asked again.
