# Installing astrolol

astrolol installs as a package on the telescope computer. It then starts by itself at every boot,
and you use it from a web browser on any phone, tablet or computer on the same network.

The package is for **Debian 13**, **Raspberry Pi OS** based on it (trixie) and **Ubuntu 26.04**,
on a Raspberry Pi (64-bit system) or a PC. On another system, install astrolol from its source
code: see the [README](../../README.md).

## 1. Add the astrolol repository

Once, on the telescope computer:

```bash
sudo curl -fsSL https://apt.astrolol.lol/astrolol.gpg -o /etc/apt/keyrings/astrolol.gpg
sudo tee /etc/apt/sources.list.d/astrolol.sources <<'EOF'
Types: deb
URIs: https://apt.astrolol.lol
Suites: nightly
Components: main
Signed-By: /etc/apt/keyrings/astrolol.gpg
EOF
sudo apt update
```

For now there are only nightly builds: they follow development, so they get new features first
and may sometimes break. Update often.

## 2. Install the device drivers

astrolol talks to cameras, mounts and focusers through INDI. The INDI that comes with Debian and
Ubuntu is old and has few drivers, so install a recent one with the drivers for most equipment:

- **Debian 13 and Raspberry Pi OS**, from Astroberry:

  ```bash
  curl -fsSL https://astroberry.io/debian/astroberry.asc | sudo gpg --dearmor -o /etc/apt/keyrings/astroberry.gpg
  sudo curl -fsSL https://astroberry.io/debian/astroberry.sources -o /etc/apt/sources.list.d/astroberry.sources
  sudo apt update
  sudo apt install indi-bin indi-3rdparty-drivers
  ```

- **Ubuntu 26.04**, from the INDI project:

  ```bash
  sudo add-apt-repository ppa:mutlaqja/ppa
  sudo apt install indi-bin indi-3rdparty-drivers
  ```

Without them, astrolol still installs the basic INDI from your system. Equipment that astrolol
drives itself (Sky-Watcher mounts through [EQMOD](../../astrolol/plugins/eqmod/docs/en.md), ASCOM
Alpaca devices on the network) needs no INDI driver.

## 3. Install astrolol

```bash
sudo apt install astrolol
```

astrolol starts right away. In a browser, open `http://<telescope computer>:8000`, for example
`http://raspberrypi.local:8000`, and carry on with [Getting started](getting-started.md).

The ASTAP plate solver comes with it. For [Plate Solving](../../astrolol/plugins/platesolve/docs/en.md),
also install its star database (D05, about 100 MB, suits most setups):

```bash
curl -fLo /tmp/d05.deb https://master.dl.sourceforge.net/project/astap-program/star_databases/d05_star_database.deb
sudo apt install /tmp/d05.deb
```

It may say `chmod: cannot access '/opt/astap/astap'`: that is harmless.

## Optional extras

| For | Install |
|---|---|
| Guiding with [PHD2](../../astrolol/plugins/phd2/docs/en.md) | `sudo apt install phd2` (Debian and Raspberry Pi OS, from Astroberry) |
| [Bluetooth serial](../../astrolol/plugins/bluetooth_serial/docs/en.md) adapters | `sudo apt install bluez` |
| Wi-Fi and hotspot on the [System](../../astrolol/plugins/system/docs/en.md) page | `sudo apt install network-manager` (already there on Raspberry Pi OS) |

Until you turn on the [Security](../../astrolol/plugins/security/docs/en.md) plugin, anyone on the
network can operate the rig: keep astrolol on a network you trust, and never open its port to the
internet.

## HTTPS, with nginx in front

With the nginx web server in front of it, astrolol answers on the usual web address
(`https://raspberrypi.local/`, no `:8000`) and over HTTPS. Use HTTPS if you turn on sign-in:
over plain HTTP, passwords are readable by anyone on the network.

```bash
sudo apt install nginx
sudo /usr/share/astrolol/nginx/install-nginx-https.sh
```

The script creates a certificate for this computer's name, `<name>.local` and its addresses, and
sets nginx up with it. Run it again after changing the computer's name or address.

Open `https://<telescope computer>.local/`. The browser warns that the certificate is not
trusted, because only this computer vouches for it: accept the exception once on each device, or
import `/etc/nginx/ssl/astrolol.crt` as a trusted certificate on your phones and computers.

For plain HTTP on port 80 instead:

```bash
sudo apt install nginx
sudo cp /usr/share/astrolol/nginx/nginx-http.conf /etc/nginx/sites-available/astrolol
sudo ln -s /etc/nginx/sites-available/astrolol /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

## Updating

```bash
sudo apt update && sudo apt upgrade
```

astrolol restarts with the new version.

## Where things are

| What | Where |
|---|---|
| Settings, profiles, users, logs | `/var/lib/astrolol` |
| Captured images | `/var/lib/astrolol/images` |
| Start-up configuration | `/etc/astrolol/astrolol.toml` |

astrolol runs as its own user, `astrolol`, which can use serial ports and USB cameras. The
configuration file holds the few settings read at start-up, such as another folder for images
(`images_dir`, for example a USB drive the `astrolol` user can write to). After changing it:

```bash
sudo systemctl restart astrolol
```

To check that astrolol runs, or to see its messages when it does not start:

```bash
systemctl status astrolol
journalctl -u astrolol -e
```

## Removing astrolol

```bash
sudo apt remove astrolol
```

Your settings, profiles and images stay in `/var/lib/astrolol`; delete the folder if you do not
need them any more.
