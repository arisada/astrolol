# mDNS

*Plugin: mDNS Discovery.* Announces astrolol on the local network, so apps (such as the
Android app) find it without you typing an IP address.

astrolol cannot guess the address clients should use, especially when it sits behind a web
server that provides HTTPS, so you set it here:

| Setting | |
|---|---|
| Instance name | The name shown in apps. Defaults to the computer's name. |
| Advertised host | An IP address or host name. Leave blank to use the computer's local address. |
| Advertised port | **Required**: nothing is announced until it is set. 443 behind a web server with HTTPS, 8000 without one. |
| Scheme | `http` or `https`. |

**Use this page's address** fills the fields from the address you used to open astrolol,
which is usually right.

Click **Save**, then **Restart astrolol** for the change to take effect.
