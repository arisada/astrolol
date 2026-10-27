# System

*Plugin: System.* Looks after the computer astrolol runs on, typically a Raspberry Pi in the
field.

## Health

- **System**: platform, uptime, CPU load, memory, root disk, temperature.
- **Power**: whether the computer is or has been **under-voltage**, **throttled**,
  **frequency capped** or at its **soft temperature limit**, now and since boot. An
  underpowered Raspberry Pi corrupts downloads and drops USB devices: the status bar shows a
  warning chip when it happens. **Monitor throttling** writes a warning in the logs too, at the
  chosen **Check interval**.
- **Storage**: free space. Check it before a long night.
- **USB Devices**: what is plugged in, to check that a camera or mount is seen at all.

## Network

Needs NetworkManager on the computer.

- The current connection: **Wi-Fi** (network name, IP address, gateway), **Hotspot**, or
  **Offline**.
- **Scan Networks**, pick one, type the **Password** and **Connect**.
- **Start Hotspot** turns the computer into a Wi-Fi access point, for the field where there is
  no network: connect your phone to it and open astrolol. **Stop Hotspot** returns to the usual
  network. **Hotspot Settings**: network name, password, interface.
- **Network at startup** chooses what happens without you: **Automatic** joins a known Wi-Fi
  network (at home) and opens the hotspot when none is in range (in the field); **Wi-Fi only**
  never opens it by itself; **Hotspot** always opens it. After each boot, **Wi-Fi first for**
  keeps the hotspot closed so your home network can always connect: that is your way in if the
  hotspot ever misbehaves. If Wi-Fi is lost while running, it waits **Wait after losing Wi-Fi**
  before opening the hotspot. A cable connection counts as connected. A hotspot you stopped
  yourself is not reopened until you change this setting. Back home, restart the computer or
  press **Stop Hotspot** to return to your home network.
- **Saved WiFi Connections**: networks it knows, with auto-connect or manual; delete those you
  no longer need.

The status bar shows the network mode, so you know which network to join.

## Hostname, time and time zone

- **Hostname**: the computer's network name (a reboot is needed for it to take full effect).
- **Time & Timezone**: local time, UTC, time zone and whether the clock is synchronised. A
  correct time and time zone matter for every sky calculation; in the field without Internet,
  check the time before you start.

## Controls

**Restart App**, **Reboot Device**, **Shutdown Device**. Click once to arm, again to confirm.
Reboot and shutdown need the permissions listed under **Permissions**.

## Development

Shows the installed version. **Git pull** and **Rebuild UI** update an installation made from
the source code. Restart the app afterwards to run the new server code; reload the page after a
UI rebuild. An astrolol installed as a system package has no buttons here: it updates with the
system's software updates (`sudo apt upgrade`).

## Permissions

Which machine settings astrolol may change: the network (Wi-Fi, access point), the host name,
the time zone, reboot and shutdown. Installed as a system package, astrolol has them all. Installed
from the source code, **How to allow the missing ones** gives the command to run once on the
computer, as an administrator; the change applies at once.
