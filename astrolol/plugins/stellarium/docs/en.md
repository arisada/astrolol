# Stellarium Server

*Plugin: Stellarium Server.* Shows where the telescope points in
[Stellarium](https://stellarium.org/), and lets you send it to an object from there.
Coordinates are exchanged in J2000. For SkySafari, Cartes du Ciel and other programs, use the
[LX200 Server](../../lx200/docs/en.md).

Click **Start**; the page shows the **Port** and the number of **Clients**.

In Stellarium (replace `astrolol-host` with the address of the telescope computer):

1. **Plugins → Telescope Control**: enable the plugin, then configure it.
2. **Add a new telescope**.
3. *Telescope controlled by*: **3rd party software or remote computer**.
4. *Connection type*: **TCP**. *Host*: `astrolol-host`, *Port*: the port shown in astrolol.
5. Keep the coordinate system on **J2000** (the default).
6. Save and connect. The telescope reticle appears on the sky.

To slew: right-click an object → *Current object* → **Slew telescope**.
