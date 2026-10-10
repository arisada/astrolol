# Raspberry Pi deployment guide

Run astrolol on a Raspberry Pi (or any Debian-based mini-PC) at the telescope so that it
starts at boot, restarts if it ever exits, and is reachable from your phone or laptop over
HTTPS.

What you end up with:

```
browser ──https:443──▶ nginx ──▶ astrolol (127.0.0.1:8000, systemd service, user "astrolol")
                         └────▶ ui/dist files served directly
                                       │
                                       └──▶ indiserver (started by astrolol) ──▶ USB/serial devices
```

The ready-made files live in [`deploy/`](../deploy):

| File | Purpose |
|---|---|
| `astrolol.service` | systemd unit: starts at boot, respawns on exit |
| `nginx-http.conf` | nginx in front of astrolol, plain HTTP |
| `nginx-https.conf` | the same with HTTPS (self-signed certificate) |
| `install-nginx-https.sh` | installs the HTTPS config and creates the certificate |

Each file explains its options in its own header comment. This guide puts them in order.

## 1. Before you start

- **Hardware:** a Raspberry Pi 4 or 5 (64-bit Raspberry Pi OS, Bookworm or later) is
  recommended. Imaging pipelines and plate solving are noticeably slower on older boards.
- **Network:** the Pi and your clients on the same network, or the Pi acting as an access
  point (System page, if you use the `system` plugin).
- **Security:** astrolol has **no authentication**. Keep it on a trusted network or behind
  a VPN, and never forward its port to the internet. See *Security* in the
  [README](../README.md#security). HTTPS encrypts the traffic; it does not authenticate users.

Everything below is run on the Pi, over SSH or a keyboard.

## 2. System packages

```bash
sudo apt-get update
sudo apt-get install -y git python3-venv python3-pip nodejs npm indi-bin nginx openssl
```

- `indi-bin` provides `indiserver`, which astrolol starts and stops itself.
- Add the INDI drivers for your equipment: `sudo apt-get install indi-full` for everything,
  or only the driver packages you need (`apt search indi-`). On a Raspberry Pi, the
  Astroberry repository described in the README also carries up-to-date INDI packages.
- Optional: `astap-cli gsc` for plate solving, `bluez bluez-tools` for Bluetooth serial
  devices. See the README's Requirements section.

## 3. The service account

A dedicated, login-less user runs astrolol. It needs access to the serial and USB devices
of your equipment:

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin astrolol
sudo usermod -aG dialout,plugdev,video astrolol
# Only if you use Bluetooth serial devices:
# sudo usermod -aG bluetooth astrolol
```

`dialout` covers serial ports (EQMOD cables, USB-serial focusers), `plugdev` and `video`
cover USB cameras. astrolol keeps its settings, profiles and logs in
`/home/astrolol/.astrolol/`.

## 4. Install astrolol

Everything lives in the service user's home directory:

```
/home/astrolol/venv         Python environment with astrolol installed
/home/astrolol/astrolol     git checkout, including the built UI (ui/dist)
/home/astrolol/.astrolol    settings, profiles, logs (created at first run)
```

astrolol is not on PyPI yet, so for now it is installed from a git checkout into the
venv. Once it is published, the checkout and the UI build step go away and this section
becomes `python3 -m venv /home/astrolol/venv && /home/astrolol/venv/bin/pip install astrolol`;
the service and nginx steps stay the same.

The checkout is owned by the service user. That matters: the *Development* section of
the System page runs `git pull` and rebuilds the UI as that user.

```bash
sudo -u astrolol git clone https://github.com/arisada/astrolol /home/astrolol/astrolol

# Python environment (the `-e` links it to the checkout, so updates are a git pull)
sudo -u astrolol python3 -m venv /home/astrolol/venv
sudo -u astrolol /home/astrolol/venv/bin/pip install -e /home/astrolol/astrolol

# Web UI (a few minutes on a Pi)
cd /home/astrolol/astrolol/ui
sudo -u astrolol npm install
sudo -u astrolol npm run build
```

> On a slow board (Pi Zero, Pi 3) you can build the UI on another machine and copy it:
> `rsync -a ui/dist/ pi:/home/astrolol/astrolol/ui/dist/` (then
> `chown -R astrolol:astrolol` it).

Quick check that it starts, then stop it with Ctrl-C:

```bash
sudo -u astrolol -H /home/astrolol/venv/bin/astrolol
# in another terminal:  curl http://localhost:8000/health
```

## 5. Start at boot (systemd)

```bash
sudo cp /home/astrolol/astrolol/deploy/astrolol.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now astrolol
```

The unit file already matches the layout above (`User=astrolol`,
`ExecStart=/home/astrolol/venv/bin/astrolol`). Edit it if you chose other paths; its header
comment lists what to change. It respawns astrolol 3 seconds after any exit and
never gives up retrying.

```bash
systemctl status astrolol          # is it running?
journalctl -u astrolol -f          # live output
sudo systemctl restart astrolol    # after editing settings or updating
```

Restarting from the web UI (System page → Restart App, or `POST /admin/restart`) also
works under systemd.

At this point `http://<pi-address>:8000/` already serves the full UI. The next step puts
nginx in front of it for HTTPS on the standard port.

## 6. HTTPS with nginx

```bash
sudo chmod o+x /home/astrolol      # lets nginx reach the UI files (see below)
sudo /home/astrolol/astrolol/deploy/install-nginx-https.sh
```

The script:

1. asks the installed astrolol where its UI build is (`/home/astrolol/astrolol/ui/dist`),
2. creates a self-signed certificate valid for the Pi's host name, `<hostname>.local` and its
   IPv4 addresses (it is kept on re-run while it still covers them),
3. installs `nginx-https.conf` with those paths filled in, disables nginx's default site,
4. checks the web server user can read the UI files, tests the config and reloads nginx.

Re-run it if you change the host name or IP address. `--help` lists the options (extra
names with `--name`, `--dry-run`, …).

Open `https://<hostname>.local/`. The browser warns that the certificate is not trusted,
because nobody but the Pi vouches for it. Either accept the exception once per device, or
import `/etc/nginx/ssl/astrolol.crt` as a trusted certificate on your clients. Some browser
features (installing the UI as an app, its offline cache) only work on a trusted HTTPS page.

Port 80 redirects to HTTPS. If you prefer plain HTTP, skip the script and install
`deploy/nginx-http.conf` by hand; its header lists the steps.

nginx serves the files in `ui/dist` itself and forwards everything else, including the
WebSocket, to astrolol. After rebuilding the UI nothing needs reloading.

If nginx answers **403**, the web server user (`www-data`) cannot read `ui/dist`. Home
directories are often private (mode 700 or 750); `chmod o+x /home/astrolol` lets other
users walk through the directory to reach the UI without letting them list its contents.
Alternatively, `sudo setfacl -m u:www-data:x /home/astrolol` grants only nginx that access.

## 7. Optional: let the System page manage the Pi

The `system` plugin can configure Wi-Fi/access-point mode (through NetworkManager) and
reboot or shut the Pi down. It runs `sudo` for these, so grant exactly those commands to the
service user:

```bash
command -v nmcli reboot shutdown          # note the full paths
sudo visudo -f /etc/sudoers.d/astrolol
```

```
astrolol ALL=(ALL) NOPASSWD: /usr/bin/nmcli
astrolol ALL=(ALL) NOPASSWD: /usr/sbin/reboot
astrolol ALL=(ALL) NOPASSWD: /usr/sbin/shutdown
```

Use the paths printed by `command -v`. The plugin reports in its page whether each
permission is in place. Without it, the rest of astrolol works normally.

## 8. Updating

From the web UI: System page → Development fast-forwards the checkout (`git pull --ff-only`) and
rebuilds the UI. Then restart astrolol (Restart App on the same page).

By hand:

```bash
cd /home/astrolol/astrolol
sudo -u astrolol git pull --ff-only
sudo -u astrolol /home/astrolol/venv/bin/pip install -e .   # only when dependencies changed
(cd ui && sudo -u astrolol npm install && sudo -u astrolol npm run build)
sudo systemctl restart astrolol
```

## 9. Troubleshooting

| Symptom | Check |
|---|---|
| Service keeps restarting | `journalctl -u astrolol -n 100`. A `No such file` / `ModuleNotFoundError` means `ExecStart` points at an environment without astrolol installed |
| UI shows "ui/dist not found" in the log | Build the UI (step 4), or set `Environment=ASTROLOL_UI_DIST=...` in the unit |
| nginx `502 Bad Gateway` | astrolol is not running on port 8000: `systemctl status astrolol` |
| nginx `403 Forbidden` | See the note at the end of step 6 |
| Live updates stop after a while | A proxy in front of nginx is closing idle WebSockets. The shipped config allows an hour of idle time |
| Camera or mount not found | `groups astrolol` should list `dialout plugdev video`; unplug and replug the device, then restart the service. Group changes need a service restart |
| Certificate warning returns after a name/IP change | Re-run `install-nginx-https.sh` and trust the new certificate |
| Settings, profiles, logs | `/home/astrolol/.astrolol/` (`profiles.json`, `astrolol.log`) |
