# mDNS

*Plugin: mDNS Discovery.* Announces astrolol on the local network, so apps (such as the
Android app) find it without you typing an IP address.

The server is announced under this computer's name (`<name>.local`). The only things to set
are the port and scheme, which differ when a web server provides HTTPS in front of astrolol:

| Setting | |
|---|---|
| Instance name | The name shown in apps. Defaults to the computer's name. |
| Advertised port | Leave blank for astrolol's own port (8000). Set 443 behind a web server with HTTPS. |
| Scheme | `http` or `https`. |

**Use this page's address** fills the port and scheme from the address you used to open astrolol,
which is usually right.

Click **Save**, then **Restart astrolol** for the change to take effect.
