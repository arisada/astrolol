# LX200 Server

*Plugin: LX200 Server.* Pretends to be a Meade LX200 telescope over the network, which almost
every planetarium program understands: SkySafari, Cartes du Ciel, Stellarium, TheSkyX,
Voyager… The program shows where the telescope points and can send it to an object.
Coordinates are exchanged in J2000. For Stellarium you can also use the
[Stellarium Server](../../stellarium/docs/en.md).

Click **Start**; the page shows the **Port** and the connected clients.

Replace `astrolol-host` below with the address of the telescope computer.

| Program | Settings |
|---|---|
| SkySafari | Settings → Telescope → Setup. Type **Meade LX200 Classic**, mount **Alt-Az** or **Equatorial**, connect via **WiFi** to `astrolol-host` and the port. |
| Cartes du Ciel | Telescope → Setup, driver **Meade LX200**, connection **TCP**, host `astrolol-host`, the port. |
| Stellarium | Telescope Control → Add telescope, type **TCP**, host `astrolol-host`, the port. |

**GoTo** slews the mount, **Sync** corrects its pointing, **Stop / Abort** halts a slew.
