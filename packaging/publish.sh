#!/usr/bin/env bash
# publish.sh — add .deb files to the apt repository and push it to apt.astrolol.lol.
#
#   packaging/publish.sh [--suite nightly|stable] [--no-push] DEB...
#
# Maintainer only. The repository's location, its working copy and the signing key's GnuPG home
# come from local/apt.env in this checkout (not committed): ASTROLOL_APT_DIR, ASTROLOL_APT_SITE,
# GNUPGHOME. Needs: reprepro, gpg, git.
set -euo pipefail

suite="nightly" push=1 debs=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --suite) suite="$2"; shift 2 ;;
        --no-push) push=""; shift ;;
        -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "unknown option: $1" >&2; exit 2 ;;
        *) debs+=("$1"); shift ;;
    esac
done
[[ ${#debs[@]} -gt 0 ]] || { echo "usage: $0 [--suite nightly|stable] DEB..." >&2; exit 2; }

env_file="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)/local/apt.env"
[[ -f "$env_file" ]] || { echo "$env_file missing: publishing needs the maintainer's setup" >&2; exit 1; }
# shellcheck source=/dev/null
source "$env_file"
base="${ASTROLOL_APT_DIR:?}" site="${ASTROLOL_APT_SITE:?}"
export GNUPGHOME="${GNUPGHOME:?}"
[[ -f "$base/conf/distributions" ]] || { echo "$base/conf/distributions missing" >&2; exit 1; }
[[ -d "$site/.git" ]] || { echo "$site is not a git checkout" >&2; exit 1; }

for deb in "${debs[@]}"; do
    reprepro -b "$base" includedeb "$suite" "$deb"
done
reprepro -b "$base" export "$suite"
reprepro -b "$base" list "$suite"

# The site: what reprepro publishes and the public key.
key_id="$(sed -n 's/^SignWith: *//p' "$base/conf/distributions" | head -1)"
rsync -a --delete --exclude .git --exclude CNAME --exclude index.html --exclude astrolol.gpg \
    "$base/dists" "$base/pool" "$site/"
gpg --export "$key_id" > "$site/astrolol.gpg"
echo "apt.astrolol.lol" > "$site/CNAME"
touch "$site/.nojekyll"   # serve files as they are (Jekyll would skip some)
[[ -f "$site/index.html" ]] || cp "$(dirname "$0")/apt-index.html" "$site/index.html"

cd "$site"
git checkout -q --orphan publish
git add -A
git commit -q -m "astrolol apt repository, $(date -u +%Y-%m-%dT%H:%MZ)"
git branch -q -M main
if [[ -n "$push" ]]; then
    git push -q -f origin main
    echo "== pushed: https://apt.astrolol.lol"
else
    echo "== committed in $site, not pushed (--no-push)"
fi
