#!/usr/bin/env bash
# smoke-test.sh — install a built astrolol .deb in a clean distro and check that it runs.
#
#   packaging/smoke-test.sh DEB [--runner docker|podman|"sudo docker"] [--image IMAGE] [--platform PLATFORM]
#
#   IMAGE     debian:trixie (default) or ubuntu:26.04
#   PLATFORM  linux/amd64 (default) or linux/arm64 (needs qemu-user-static and binfmt on the host)
#
# Checks: apt resolves every dependency from the distro alone, the service account and data
# directory exist, the files are in place, and astrolol starts as its user, answers /health and
# serves the web UI and the configuration file's data_dir is used. No systemd in the container:
# astrolol is started by hand, the unit file is only checked with systemd-analyze.
set -euo pipefail

deb="" runner="" image="debian:trixie" platform="linux/amd64"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --runner) runner="$2"; shift 2 ;;
        --image) image="$2"; shift 2 ;;
        --platform) platform="$2"; shift 2 ;;
        -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "unknown option: $1" >&2; exit 2 ;;
        *) deb="$1"; shift ;;
    esac
done
[[ -f "$deb" ]] || { echo "usage: $0 DEB [options]" >&2; exit 2; }
if [[ -z "$runner" ]]; then
    for r in docker podman "sudo -n docker"; do
        if command -v "${r##* }" >/dev/null && $r info >/dev/null 2>&1; then runner="$r"; break; fi
    done
    [[ -n "$runner" ]] || { echo "no usable docker or podman" >&2; exit 1; }
fi

dir="$(cd "$(dirname "$deb")" && pwd)" name="$(basename "$deb")"
echo "== $name on $image ($platform) with $runner"
$runner run --rm --platform "$platform" -v "$dir:/debs:ro" "$image" bash -c '
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl >/dev/null
apt-get install -y -qq "/debs/'"$name"'" >/dev/null
fail() { echo "FAIL: $*"; exit 1; }

id astrolol | grep -q dialout || fail "astrolol user or its groups missing: $(id astrolol 2>&1)"
[[ -d /var/lib/astrolol/images ]] || fail "/var/lib/astrolol/images missing"
[[ "$(stat -c %U /var/lib/astrolol)" == astrolol ]] || fail "/var/lib/astrolol not owned by astrolol"
for f in /usr/bin/astrolol /etc/astrolol/astrolol.toml /usr/share/polkit-1/rules.d/50-astrolol.rules \
         /usr/lib/systemd/system/astrolol.service; do
    [[ -e "$f" ]] || fail "$f missing"
done
python3 -c "import astrolol.api.static as s; assert s.UI_DIST and s.UI_DIST.name == \"_ui\", s.UI_DIST" \
    || fail "the packaged UI is not found"
if command -v systemd-analyze >/dev/null; then
    systemd-analyze verify /usr/lib/systemd/system/astrolol.service 2>&1 | grep -v "^$" || true
fi

cd /var/lib/astrolol
runuser -u astrolol -- /usr/bin/astrolol > /tmp/astrolol.out 2>&1 &
for _ in $(seq 120); do
    curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && break
    sleep 1
done
curl -fsS http://127.0.0.1:8000/health || { cat /tmp/astrolol.out; fail "no answer on /health"; }
echo
curl -fsS -H "Accept: text/html" http://127.0.0.1:8000/ | grep -qi "<div id=\"root\"" || fail "the web UI is not served"
[[ -f /var/lib/astrolol/astrolol.log ]] || fail "data_dir from /etc/astrolol/astrolol.toml not used"
echo "OK: '"$name"' on $(. /etc/os-release; echo "$PRETTY_NAME") $(uname -m)"
'
