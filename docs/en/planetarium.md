# Planetarium servers

Two plugins let a planetarium program show where the telescope points and send it to an
object. Coordinates are exchanged in J2000. Replace `astrolol-host` below with the address of
the telescope computer.

## Stellarium Server

*Plugin: Stellarium Server.* Speaks Stellarium's own telescope protocol. Click **Start**; the
page shows the **Port** and the number of **Clients**.

In Stellarium:

1. **Plugins → Telescope Control**: enable the plugin, then configure it.
2. **Add a new telescope**.
3. *Telescope controlled by*: **3rd party software or remote computer**.
4. *Connection type*: **TCP**. *Host*: `astrolol-host`, *Port*: the port shown in astrolol.
5. Keep the coordinate system on **J2000** (the default).
6. Save and connect. The telescope reticle appears on the sky.

To slew: right-click an object → *Current object* → **Slew telescope**.

## LX200 Server

*Plugin: LX200 Server.* Pretends to be a Meade LX200 telescope over the network, which almost
every planetarium program understands: SkySafari, Cartes du Ciel, Stellarium, TheSkyX,
Voyager… Click **Start**; the page shows the **Port** and the connected clients.

| Program | Settings |
|---|---|
| SkySafari | Settings → Telescope → Setup. Type **Meade LX200 Classic**, mount **Alt-Az** or **Equatorial**, connect via **WiFi** to `astrolol-host` and the port. |
| Cartes du Ciel | Telescope → Setup, driver **Meade LX200**, connection **TCP**, host `astrolol-host`, the port. |
| Stellarium | Telescope Control → Add telescope, type **TCP**, host `astrolol-host`, the port. |

**GoTo** slews the mount, **Sync** corrects its pointing, **Stop / Abort** halts a slew.
