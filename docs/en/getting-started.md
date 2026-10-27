# Getting started

This page takes you from a fresh installation to a rig you can connect with one click. It
assumes astrolol is already installed and running on the telescope computer (see
[Installing astrolol](install.md)).

The idea in short:

- **Equipment → connections** is where devices are connected right now.
- **Equipment → inventory** is the list of everything you own: telescopes, cameras, mounts,
  your observing site…
- A **profile** picks items from the inventory and arranges them as they are physically mounted
  (site → mount → telescope → focuser → filter wheel → camera). Activating the profile connects
  all its devices.

You do this once; afterwards, an evening starts with one click on **Activate**.

## 1. Open astrolol

In a browser, go to the address of the telescope computer, for example
`http://astrolol.local:8000` or `https://astrolol.local` if it sits behind a web server. If you
turned on the [mDNS](../../astrolol/plugins/mdns/docs/en.md) plugin, apps can find it on the network by themselves.

The first page is **Imaging**. With nothing connected it says *No camera connected*. The menu
on the left lists the screens; the bar at the top shows the state of every device and **live**
when the browser is receiving updates (see [The interface](interface.md)).

If [Security](../../astrolol/plugins/security/docs/en.md) is turned on you are asked to sign in first.

## 2. Turn on the features you want

Go to **Options → Plugins** and tick the features you want, for example *Target*,
*Plate Solving*, *Autofocus*, *Sequencer*, *Viewer* and one guider (*Built-in Guider* or
*PHD2 Guiding*, not both). Then click **Restart now**. The new pages appear in the menu.

You can come back to this list any time. See [Options](options.md#plugins).

## 3. Connect a device

Go to **Equipment** and stay on the **connections** tab. Click **Load driver** and answer the
questions:

1. **What do you want to connect?** Camera, Mount, Focuser, Filter Wheel or Rotator.
2. **How is it connected?**
   - **Browse INDI drivers** for almost every commercial device. astrolol starts the INDI
     server for you.
   - **Other adapter** for drivers that come with astrolol plugins, such as the native
     [EQMOD](../../astrolol/plugins/eqmod/docs/en.md) driver for Sky-Watcher mounts, or for
     [ASCOM Alpaca](../../astrolol/plugins/alpaca/docs/en.md) devices on the network.
3. **Select manufacturer**, then **Select model**. If your device is not listed, choose
   **Enter manually…** and type the name of its INDI driver (for example `indi_asi_ccd`).
4. **Configure & connect.** astrolol shows the settings the driver offers before connecting:
   serial port, baud rate, and so on. Most devices work with the defaults. You can also give the
   device a short **Device ID**; leave it empty to get one made from its name.
5. Click **Connect**.

The device appears under **Connected**. Some drivers bring more than one device: a camera with
a built-in filter wheel, for example. Those show up as *auto-discovered*.

> Tip: to try astrolol without hardware, pick the INDI *Simulators* manufacturer: there is a
> telescope simulator, a CCD simulator, a focuser simulator and a filter wheel simulator.

## 4. Add it to the inventory

As soon as a device is connected, astrolol asks
*"… is connected — add it to your inventory?"*. Click **Import to inventory** (or **Not now**).
You can also do it later with the import button on the device row; a device already in the
inventory is marked *Already in inventory*.

The inventory remembers which driver the device uses, so a profile can connect it again later
without the wizard.

Do this for each device: mount, main camera, guide camera, focuser, filter wheel.

## 5. Add what cannot be connected

Some equipment has no driver but astrolol still needs to know about it. Open the
**inventory** tab and click **Add equipment**:

- **Observation Site**: name, latitude, longitude, altitude, time zone. Without a site astrolol
  cannot point the mount or tell you when objects rise and set, so the inventory reminds you
  until you add one.
- **Telescope / OTA**: focal length and aperture. These give the image scale used by plate
  solving and guiding. Add one for the guide scope too.

While you are here, edit the cameras to set the **pixel size** and a **default gain**, and the
filter wheel to give its **filter names** (comma-separated, in slot order: `L, R, G, B, Ha`).
These names appear everywhere you pick a filter.

## 6. Create a profile

Go to **Profiles**, click **New profile**, give it a name (*Backyard rig*) and click
**Create profile**. Open the profile and build its **equipment tree** with **Add to tree**, then
the **+** next to each item to attach what sits under it:

```
Observation Site
└── Mount
    ├── Main telescope
    │   └── Focuser
    │       └── Filter wheel
    │           └── Main camera
    └── Guide scope
        └── Guide camera
```

![A profile with its equipment tree](../images/profiles.png)

The tree is not decoration: it tells astrolol which focuser and filter wheel belong to which
camera (so the Imaging page for the main camera shows that focuser and that wheel), which
telescope gives which image scale, and where on Earth the mount stands. See
[Profiles](profiles.md) for the rules.

## 7. Activate the profile

Click **Activate**. astrolol connects every device in the tree and reports
*Profile activated* (or *Activated with errors*, with the reason for each device that failed).
The profile stays active: when astrolol restarts it reconnects it by itself.

You are ready. A typical first evening:

1. [Mount](mount.md): unpark, check tracking.
2. [Polar Align](../../astrolol/plugins/polar_align/docs/en.md) if the mount was just set up.
3. [Target](../../astrolol/plugins/target/docs/en.md): find an object, **Slew to Target**.
4. [Plate Solving](../../astrolol/plugins/platesolve/docs/en.md): **Expose & Solve** with *Sync and slew* to centre it.
5. [Autofocus](../../astrolol/plugins/autofocus/docs/en.md).
6. [Guider](../../astrolol/plugins/guider/docs/en.md) or [PHD2](../../astrolol/plugins/phd2/docs/en.md): start guiding.
7. [Imaging](imaging.md) for single frames, or the [Sequencer](../../astrolol/plugins/sequencer/docs/en.md) for the night.
