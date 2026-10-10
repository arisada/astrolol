#!/usr/bin/env bash
# install-nginx-https.sh — put nginx in front of astrolol with HTTPS.
#
# Does what the header of nginx-https.conf describes, automatically:
#   1. finds the built UI (the one the installed astrolol serves, or the path
#      you give),
#   2. creates a self-signed certificate for this machine's host name
#      (short name, name.local, fully qualified name and every IP address),
#   3. installs deploy/nginx-https.conf with those paths filled in,
#   4. checks that nginx can read the UI files, tests the config and reloads.
#
# ── USAGE (as root, from anywhere) ──────────────────────────────────────────
#   sudo apt install nginx openssl                 # once
#   (cd ui && npm install && npm run build)        # once, builds ui/dist
#   sudo deploy/install-nginx-https.sh [options]
#
# Options:
#   --ui-dist DIR     UI build directory. Default: $ASTROLOL_UI_DIST, else the
#                     one the service user's astrolol install serves, else
#                     <this checkout>/ui/dist
#   --user NAME       the service user (default: astrolol); its ~/venv is
#                     asked where the UI is
#   --name NAME       extra name for the certificate; repeatable
#   --ip ADDR         extra IP for the certificate; repeatable
#   --days N          certificate lifetime (default 3650)
#   --force-cert      recreate the certificate even if one exists
#   --keep-default    don't disable nginx's default site
#   --dry-run         show what would be done, change nothing
#
# Re-running is safe: an existing certificate is kept as long as it already
# covers every name and IP, otherwise it is recreated. Re-run after changing
# the host name or IP address. Clients must trust (or accept the warning for)
# /etc/nginx/ssl/astrolol.crt.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$SRC_DIR/nginx-https.conf"
SSL_DIR=/etc/nginx/ssl
CERT="$SSL_DIR/astrolol.crt"
KEY="$SSL_DIR/astrolol.key"

ui_dist="${ASTROLOL_UI_DIST:-}"
service_user=astrolol
days=3650
force_cert=0
keep_default=0
dry=0
extra_names=()
extra_ips=()

die()  { echo "error: $*" >&2; exit 1; }
info() { echo "==> $*"; }
run()  { if ((dry)); then echo "[dry-run] $*"; else "$@"; fi; }

while (($#)); do
    case "$1" in
        --ui-dist)      ui_dist="${2:?}"; shift 2 ;;
        --user)         service_user="${2:?}"; shift 2 ;;
        --name)         extra_names+=("${2:?}"); shift 2 ;;
        --ip)           extra_ips+=("${2:?}"); shift 2 ;;
        --days)         days="${2:?}"; shift 2 ;;
        --force-cert)   force_cert=1; shift ;;
        --keep-default) keep_default=1; shift ;;
        --dry-run)      dry=1; shift ;;
        -h|--help)      sed -n '2,/^set -e/p' "$0" | sed '$d;s/^# \{0,1\}//'; exit 0 ;;
        *)              die "unknown option: $1 (see --help)" ;;
    esac
done

((dry)) || [[ $EUID -eq 0 ]] || die "run as root (sudo $0 ...)"
command -v nginx   >/dev/null || die "nginx is not installed (sudo apt install nginx)"
command -v openssl >/dev/null || die "openssl is not installed"
[[ -f $TEMPLATE ]] || die "missing $TEMPLATE"

# ── UI build directory ─────────────────────────────────────────────────────
# Ask the installed astrolol where it finds the UI: that is the one the
# service really serves, whether it is a git checkout or a package.
if [[ -z $ui_dist ]]; then
    home="$(getent passwd "$service_user" | cut -d: -f6 || true)"
    if [[ -n $home && -x $home/venv/bin/python3 ]]; then
        ui_dist="$(cd / && "$home/venv/bin/python3" -c \
            'from astrolol.api.static import UI_DIST; print(UI_DIST or "")' 2>/dev/null || true)"
    fi
    [[ -n $ui_dist ]] || ui_dist="$SRC_DIR/../ui/dist"
fi
ui_dist="$(realpath -m "$ui_dist")"
[[ -f $ui_dist/index.html ]] \
    || die "no UI build in $ui_dist — run 'cd ui && npm run build', or pass --ui-dist DIR"
info "UI build: $ui_dist"

# ── names and addresses for the certificate ────────────────────────────────
short="$(hostname -s)"
fqdn="$(hostname -f 2>/dev/null || true)"
names=("$short" "$short.local")
[[ -n $fqdn && $fqdn != "$short" && $fqdn != localhost* ]] && names+=("$fqdn")
names+=("${extra_names[@]}")
# IPv4 only: IPv6 addresses change with privacy extensions and prefixes.
read -r -a host_ips <<<"$(hostname -I 2>/dev/null || true)"
ips=()
for a in "${host_ips[@]}"; do [[ $a =~ ^[0-9]+(\.[0-9]+){3}$ ]] && ips+=("$a"); done
ips+=("${extra_ips[@]}")

# De-duplicate, keeping order.
mapfile -t names < <(printf '%s\n' "${names[@]}" | awk 'NF && !seen[$0]++')
mapfile -t ips   < <(printf '%s\n' "${ips[@]}"   | awk 'NF && !seen[$0]++')

san=()
for n in "${names[@]}"; do san+=("DNS:$n"); done
for i in "${ips[@]}";   do san+=("IP:$i");  done
san_list="$(IFS=,; echo "${san[*]}")"
info "certificate names: ${names[*]}${ips[*]:+ | IPs: ${ips[*]}}"

# ── certificate ────────────────────────────────────────────────────────────
cert_covers_all() {
    [[ -f $CERT && -f $KEY ]] || return 1
    local have; have="$(openssl x509 -in "$CERT" -noout -ext subjectAltName 2>/dev/null)" || return 1
    openssl x509 -in "$CERT" -noout -checkend $((30 * 86400)) >/dev/null || return 1  # expires within 30 days
    local n i
    for n in "${names[@]}"; do grep -qiF "DNS:$n" <<<"$have" || return 1; done
    for i in "${ips[@]}";   do grep -qF  "IP Address:$i" <<<"$have" || return 1; done
}

if ((force_cert)) || ! cert_covers_all; then
    info "creating self-signed certificate ($days days)"
    run install -d -m 755 "$SSL_DIR"
    # openssl prints key-generation progress on stderr; only show it on failure.
    errlog="$(mktemp)"; trap 'rm -f "$errlog"' EXIT
    run openssl req -x509 -nodes -newkey rsa:2048 -days "$days" \
        -keyout "$KEY" -out "$CERT" \
        -subj "/CN=$short" -addext "subjectAltName=$san_list" 2>"$errlog" \
        || { cat "$errlog" >&2; die "openssl failed"; }
    run chmod 600 "$KEY"
else
    info "existing certificate already covers these names — keeping it"
fi

# ── nginx user must be able to read the UI ─────────────────────────────────
nginx_user="$(awk '/^[[:space:]]*user[[:space:]]/ {gsub(";",""); print $2; exit}' /etc/nginx/nginx.conf 2>/dev/null || true)"
nginx_user="${nginx_user:-www-data}"
if id "$nginx_user" >/dev/null 2>&1 && ! ((dry)); then
    if ! runuser -u "$nginx_user" -- test -r "$ui_dist/index.html"; then
        echo "warning: user '$nginx_user' cannot read $ui_dist — nginx will answer 403." >&2
        echo "         Every parent directory needs the execute bit for it, e.g." >&2
        echo "           sudo chmod o+x $(dirname "$ui_dist") ...  (or setfacl -m u:$nginx_user:x <dir>)" >&2
        echo "         Home directories (mode 700) are the usual culprit." >&2
    fi
fi

# ── nginx site file ────────────────────────────────────────────────────────
if [[ -d /etc/nginx/sites-available ]]; then
    site=/etc/nginx/sites-available/astrolol
    enabled=/etc/nginx/sites-enabled/astrolol
else
    site=/etc/nginx/conf.d/astrolol.conf     # distros without sites-enabled
    enabled=""
fi

rendered="$(sed \
    -e "s|^\([[:space:]]*root[[:space:]]\+\).*;|\1$ui_dist;|" \
    -e "s|^\([[:space:]]*ssl_certificate[[:space:]]\+\).*;|\1$CERT;|" \
    -e "s|^\([[:space:]]*ssl_certificate_key[[:space:]]\+\).*;|\1$KEY;|" \
    "$TEMPLATE")"

info "installing $site"
if ((dry)); then
    echo "[dry-run] would write $site:"; grep -E '^\s*(root|ssl_certificate)' <<<"$rendered"
else
    printf '%s\n' "$rendered" >"$site"
    [[ -z $enabled ]] || ln -sf "$site" "$enabled"
    if ! ((keep_default)) && [[ -e /etc/nginx/sites-enabled/default ]]; then
        info "disabling nginx's default site (it also listens on port 80)"
        rm -f /etc/nginx/sites-enabled/default
    fi
fi

# ── test and reload ────────────────────────────────────────────────────────
if ((dry)); then
    echo "[dry-run] nginx -t && systemctl reload nginx"
else
    nginx -t
    if systemctl is-active --quiet nginx; then systemctl reload nginx; else systemctl enable --now nginx; fi
    info "done — open https://$short.local/ (or https://${ips[0]:-$short}/)"
    echo "    astrolol itself must be running on 127.0.0.1:8000 (see deploy/astrolol.service)."
fi
