# Security

*Plugin: Security.* Controls who can see and operate the telescope. Until the first account is
created, anyone who can reach astrolol has full access. That is fine at home on a private
network, but not on a shared network (a star party, a club, a public Wi-Fi).

Use HTTPS when you turn security on: over plain HTTP, passwords travel in clear on the network.
The page warns you when the connection is not encrypted. See the
[deployment guide](../raspberry-pi-deployment.md).

## Levels

| Level | Can |
|---|---|
| read-only | Watch everything, change nothing. |
| operator | Run the telescope: slew, expose, guide, run sequences. |
| admin | Also change settings, plugins, equipment and users. |

## Turning it on

Under **Create the first account**, choose a user name and a password (at least 8 characters)
and click **Create account and turn security on**. This first account is an admin. From then on,
everyone has to sign in.

## Managing access

- **Your account**: change your password (you are then asked to sign in again).
- **Guest access**: lets people look without a password, at read-only level. Handy to show the
  session to friends or on a second screen.
- **Users** (admins only): add users with a level, **Reset password**, **Delete**. The only admin
  cannot be demoted or deleted.
- **API tokens** (admins only): let other programs and scripts use astrolol without a password.
  Give the token a name and a validity in days (or **No expiry**), click **Create token** and
  copy it at once: it is shown only once. **Revoke** cancels it.
- **Allowed origins** (admins only): web pages from these addresses may call astrolol from
  another site, using a token. One address per line.

## Locked out?

On the telescope computer, as the user that runs astrolol:

```bash
python -m astrolol.plugins.security list                # list the users
python -m astrolol.plugins.security set-password NAME   # set a user's password
python -m astrolol.plugins.security add-admin NAME      # create an admin
python -m astrolol.plugins.security reset               # remove all accounts: security off
```
