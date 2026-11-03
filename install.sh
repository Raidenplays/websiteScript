#!/usr/bin/env bash
# raidenbrundin.com installer.
# Run it on the server from the cloned folder:   sudo ./install.sh   (or as root: ./install.sh)
# Safe to run again: it keeps your settings, accounts and pages.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
DIR="$(pwd)"

G='\033[1;32m'; Y='\033[1;33m'; R='\033[1;31m'; B='\033[1m'; N='\033[0m'
say()  { echo -e "${G}==>${N} $*"; }
warn() { echo -e "${Y}!!${N}  $*"; }
die()  { echo -e "${R}ERROR:${N} $*" >&2; exit 1; }
ask()  { local a; read -rp "$(echo -e "${B}$1${N}") [${2}]: " a </dev/tty || true; echo "${a:-$2}"; }
confirm() { local a; a="$(ask "$1 (y/n)" "${2:-y}")"; [[ "$a" =~ ^[Yy] ]]; }

if [ "$(id -u)" -ne 0 ]; then
  command -v sudo >/dev/null && exec sudo bash "$0" "$@"
  die "Run this as root (type 'su -' first) or with sudo."
fi

echo -e "\n${B}raidenbrundin.com installer${N}\n"

# ---------------------------------------------------------------- 1. Docker
if ! command -v docker >/dev/null; then
  say "Docker isn't installed. Installing it now..."
  command -v curl >/dev/null || { apt-get update -qq && apt-get install -y -qq curl ca-certificates; }
  curl -fsSL https://get.docker.com | sh
fi
if ! docker compose version >/dev/null 2>&1; then
  say "Installing the Docker Compose plugin..."
  apt-get update -qq && apt-get install -y -qq docker-compose-plugin || die "Couldn't install docker-compose-plugin. Install Docker Compose v2 and run this again."
fi
systemctl enable --now docker >/dev/null 2>&1 || true
say "Docker is ready ($(docker --version | cut -d, -f1))"

# ---------------------------------------------------------------- 2. Settings (.env)
free_port() {
  local p=8080
  while ss -ltnH "sport = :$p" 2>/dev/null | grep -q .; do p=$((p + 1)); done
  echo "$p"
}
https_or_blank() {
  local v="$1"
  [ -z "$v" ] && { echo ""; return; }
  [[ "$v" =~ ^https:// ]] || v="https://$v"
  echo "$v"
}

if [ -f .env ] && confirm "Found existing settings (.env). Keep them?" y; then
  say "Keeping your settings."
  grep -q '^WEB_PORT=' .env || echo "WEB_PORT=$(free_port)" >> .env
else
  echo -e "\nA few questions. Press Enter to accept the [default], or leave optional ones blank.\n"
  DOMAIN="$(ask "Website address" "raidenbrundin.com")"
  DOMAIN="${DOMAIN#https://}"; DOMAIN="${DOMAIN#http://}"; DOMAIN="${DOMAIN%%/*}"
  if confirm "Is the site served through a Cloudflare Tunnel?" y; then CF=1; else CF=0; fi
  EMAIL="$(ask "Contact email shown on the site (optional)" "")"
  if [ -n "$EMAIL" ] && ! [[ "$EMAIL" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[A-Za-z]{2,}$ ]]; then warn "That email doesn't look right, leaving it blank."; EMAIL=""; fi
  LINKEDIN="$(https_or_blank "$(ask "LinkedIn profile link (optional)" "")")"
  GITHUB="$(https_or_blank "$(ask "GitHub profile link (optional)" "")")"
  DISCORD="$(https_or_blank "$(ask "Discord invite link (optional)" "")")"
  SLINK="$(https_or_blank "$(ask "SlinkGrenade's channel link (optional)" "")")"
  PORT="$(free_port)"
  cat > .env <<EOF
# Made by install.sh on $(date). Edit and run: ./site.sh restart
SITE_ORIGIN=https://${DOMAIN}
COOKIE_SECURE=1
TRUST_CLOUDFLARE=${CF}
WEB_PORT=${PORT}
CONTACT_EMAIL=${EMAIL}
LINKEDIN_URL=${LINKEDIN}
GITHUB_URL=${GITHUB}
DISCORD_INVITE=${DISCORD}
SLINKGRENADE_URL=${SLINK}
EOF
  say "Saved settings to .env"
fi
chmod 600 .env
PORT="$(grep '^WEB_PORT=' .env | cut -d= -f2)"
DOMAIN="$(grep '^SITE_ORIGIN=' .env | cut -d= -f2 | sed 's#https://##')"

# ---------------------------------------------------------------- 3. Build + start (creates the database on first start)
say "Building and starting the website (the first time takes a minute or two)..."
docker compose up -d --build

say "Waiting for it to come up..."
for i in $(seq 1 60); do
  curl -fsS "http://127.0.0.1:${PORT}/api/me" >/dev/null 2>&1 && break
  [ "$i" -eq 60 ] && { docker compose logs --tail=40; die "The website didn't start. The log is above."; }
  sleep 1
done
say "Website is running on http://127.0.0.1:${PORT} (only reachable from this machine)"

# ---------------------------------------------------------------- 4. Admin account
if docker compose exec -T website python -m app.manage has-admin; then
  say "An admin account already exists."
else
  echo
  say "Let's make your admin account (this is what you log in to the Site Manager app with)."
  NAME="$(ask "Admin username" "Raiden")"
  until docker compose exec website python -m app.manage create-admin "$NAME"; do warn "Let's try that again."; done
fi

# ---------------------------------------------------------------- 5. Nightly backups
chmod +x site.sh
if [ ! -f /etc/cron.d/raiden-website ] && confirm "Back up accounts, pages and pics every night (keeps the last 14)?" y; then
  echo "30 3 * * * root ${DIR}/site.sh backup --quiet" > /etc/cron.d/raiden-website
  say "Nightly backups set up. They go in ${DIR}/backups"
fi

# ---------------------------------------------------------------- 6. Cloudflare Tunnel
CF_CONTAINER="$(docker ps --format '{{.Names}} {{.Image}}' | awk '/cloudflare\/cloudflared|cloudflared/ {print $1; exit}')"
echo
if [ -n "$CF_CONTAINER" ]; then
  docker network connect raiden-website_default "$CF_CONTAINER" 2>/dev/null || true
  say "Found cloudflared running in Docker ($CF_CONTAINER) and connected it to the website."
  echo -e "    In your Cloudflare dashboard, set the tunnel's ${B}${DOMAIN}${N} service to:  ${B}http://raiden-website:8080${N}"
  warn "If that cloudflared container ever gets recreated, run ./install.sh again to reconnect it."
elif command -v cloudflared >/dev/null || systemctl list-units --type=service 2>/dev/null | grep -q cloudflared; then
  say "Found cloudflared installed on this machine."
  echo -e "    Point the tunnel's ${B}${DOMAIN}${N} service at:  ${B}http://localhost:${PORT}${N}"
  echo "    (Cloudflare dashboard > Zero Trust > Networks > Tunnels > your tunnel > Public Hostname)"
else
  warn "Didn't find cloudflared. Point whatever serves ${DOMAIN} at http://localhost:${PORT}"
fi

cat <<EOF

$(echo -e "${G}All done!${N}")

  Your site:        https://${DOMAIN}   (once the tunnel points at it)
  Edit everything:  Raiden Site Manager app on your PC, log in with your admin account

  Handy commands (run from ${DIR}):
    ./site.sh status          is it running?
    ./site.sh update          get the latest code from GitHub and restart
    ./site.sh backup          back up now
    ./site.sh export-pages    save every page to a file
    ./site.sh import-pages F  upload every page from a file
    ./site.sh help            everything else

EOF
