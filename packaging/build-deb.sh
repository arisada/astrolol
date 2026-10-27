#!/usr/bin/env bash
# build-deb.sh — build astrolol's .deb from a git commit.
#
#   packaging/build-deb.sh [--runner docker|podman|"sudo docker"|host] [--ref REF] [--out DIR] [--nocheck]
#
# Steps (see local/packaging_plan.md):
#   1. the web UI: npm ci, typecheck, lint, test, build      (here, needs network for npm)
#   2. the source tree: `git archive REF` + the built UI + debian/changelog for this version
#   3. dpkg-buildpackage -b in a clean Debian 13 (trixie), the oldest target: the test suite runs
#      there against Debian's own Python libraries
#   4. lintian
# The result, astrolol_<version>_all.deb, is in --out (default: packaging/out).
#
# Version: pyproject's version for a tagged commit (v0.2.0 → 0.2.0-1), otherwise a nightly
# 0.2.0~git20261027.1a2b3c4-1, which sorts before the 0.2.0 release.
#
# --runner: docker, podman or "sudo docker" runs step 3 and 4 in a debian:trixie container (default:
# the first that works); host builds on this machine, which then needs the Build-Depends of debian/control.
set -euo pipefail

runner="" ref="HEAD" out="" nocheck=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --runner) runner="$2"; shift 2 ;;
        --ref) ref="$2"; shift 2 ;;
        --out) out="$2"; shift 2 ;;
        --nocheck) nocheck=1; shift ;;
        -h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

repo="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
out="${out:-$repo/packaging/out}"
image="debian:trixie"

if [[ -z "$runner" ]]; then
    for r in docker podman "sudo -n docker"; do
        if command -v "${r##* }" >/dev/null && $r info >/dev/null 2>&1; then runner="$r"; break; fi
    done
    [[ -n "$runner" ]] || { echo "no usable docker or podman: pass --runner host, or see packaging/README.md" >&2; exit 1; }
fi

# ── Version ────────────────────────────────────────────────────────────────────
commit="$(git -C "$repo" rev-parse --short "$ref")"
upstream="$(git -C "$repo" show "$ref:pyproject.toml" | sed -n 's/^version = "\(.*\)"/\1/p' | head -1)"
if git -C "$repo" describe --exact-match --tags "$ref" 2>/dev/null | grep -qx "v$upstream"; then
    version="$upstream-1" dist="stable"
else
    date="$(git -C "$repo" show -s --format=%cd --date=format:%Y%m%d "$ref")"
    version="$upstream~git$date.$commit-1" dist="nightly"
fi
echo "== astrolol $version ($dist) from $commit, runner: $runner"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
src="$work/astrolol-${version%-*}"

# ── 1. Web UI, from the same commit ────────────────────────────────────────────
git -C "$repo" archive --format=tar --prefix="$(basename "$src")/" "$ref" | tar -x -C "$work"
echo "== web UI"
(
    cd "$src/ui"
    npm ci --no-audit --no-fund
    npm run typecheck
    npm run lint
    npm run test
    npm run build
    rm -rf node_modules
)
[[ -f "$src/ui/dist/index.html" ]] || { echo "UI build produced no index.html" >&2; exit 1; }

# ── 2. Changelog for this version ──────────────────────────────────────────────
author="$(git -C "$repo" show -s --format='%an <%ae>' "$ref")"
cat > "$src/debian/changelog" <<EOF
astrolol ($version) $dist; urgency=medium

  * Built from git commit $commit.

 -- $author  $(date -R)
EOF

# ── 3 + 4. Binary package, then lintian ────────────────────────────────────────
mkdir -p "$out"
build_cmd="set -e
cd /build/$(basename "$src")
export DEB_BUILD_OPTIONS='${nocheck:+nocheck}'
dpkg-buildpackage -b -us -uc
cd /build
lintian --info --no-tag-display-limit ./*.changes || true"

if [[ "$runner" == host ]]; then
    (
        cd "$src"
        DEB_BUILD_OPTIONS="${nocheck:+nocheck}" dpkg-buildpackage -b -us -uc
        cd "$work" && { lintian --info --no-tag-display-limit ./*.changes || true; }
    )
else
    $runner run --rm -v "$work:/build" "$image" bash -c "set -e
        trap 'chown -R $(id -u):$(id -g) /build' EXIT
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq
        apt-get install -y -qq --no-install-recommends devscripts equivs lintian >/dev/null
        cd /build/$(basename "$src") && mk-build-deps -i -r -t 'apt-get -y -qq --no-install-recommends' debian/control >/dev/null
        rm -f /build/$(basename "$src")/astrolol-build-deps_*
        $build_cmd"
fi

cp "$work"/astrolol_"${version}"_all.deb "$work"/astrolol_"${version}"_*.buildinfo "$out"/
echo "== $out/astrolol_${version}_all.deb"
