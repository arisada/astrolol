# Packaging

astrolol ships as one `Architecture: all` `.deb` for Debian 13 / Raspberry Pi OS (trixie) and
Ubuntu 26.04, on any CPU. It depends on the distro's own Python libraries; the only third-party
code it carries is the patched indipyclient (`astrolol/_vendor/`) and the built web UI
(`astrolol/_ui/` in the installed package, from `ui/dist`).

| File | What |
|---|---|
| `debian/` | the package: control, rules, the systemd unit, the service account (sysusers), `/var/lib/astrolol` (tmpfiles), `/etc/astrolol/astrolol.toml` |
| `deploy/50-astrolol.rules` | polkit rule, installed in `/usr/share/polkit-1/rules.d/` |
| `hatch_build.py` | puts `ui/dist` into the wheel as `astrolol/_ui` |
| `build-deb.sh` | builds the `.deb` from a git commit (UI, then `dpkg-buildpackage` in Debian 13) |
| `smoke-test.sh` | installs a `.deb` in a clean Debian 13 or Ubuntu 26.04 and checks it runs |
| `publish.sh` | adds `.deb` files to the apt repository at apt.astrolol.lol (maintainer only) |
| `apt-index.html` | the repository's home page (install instructions) |

## Building

```bash
packaging/build-deb.sh                 # HEAD → packaging/out/astrolol_<version>_all.deb
packaging/build-deb.sh --ref v0.2.0    # a release
packaging/build-deb.sh --nocheck       # skip the test suite in the package build
```

The build works from **committed** files (`git archive`): commit first. It needs `npm` here,
and docker or podman to build in a clean Debian 13 (`--runner host` builds on this machine
instead, with the Build-Depends of `debian/control` installed).

Versions: a commit tagged `v<version of pyproject.toml>` gives `<version>-1`; any other commit a
nightly `<version>~git<date>.<commit>-1`, which sorts before that release.

The package build runs the unit and plugin tests against Debian 13's Python libraries, the
oldest astrolol supports. A test failing there and not in development usually means the code
uses something newer than Debian 13 ships.

## Testing a package

```bash
packaging/smoke-test.sh packaging/out/astrolol_*_all.deb
packaging/smoke-test.sh packaging/out/astrolol_*_all.deb --image ubuntu:26.04
packaging/smoke-test.sh packaging/out/astrolol_*_all.deb --platform linux/arm64   # needs qemu-user-static
```

## Publishing

```bash
packaging/publish.sh packaging/out/astrolol_<version>_all.deb          # → nightly
packaging/publish.sh --suite stable packaging/out/astrolol_0.2.0-1_all.deb
```

Publishing is for the maintainer: it needs the repository's signing key and its configuration
(`local/apt.env`), which are not part of this repository.
