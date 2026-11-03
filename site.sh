#!/usr/bin/env bash
# Day-to-day helper for raidenbrundin.com. Run from anywhere: /path/to/site.sh <command>
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
DIR="$(pwd)"
VOLUME="raiden-website_website-data"
G='\033[1;32m'; R='\033[1;31m'; N='\033[0m'
say() { echo -e "${G}==>${N} $*"; }
die() { echo -e "${R}ERROR:${N} $*" >&2; exit 1; }
port() { grep '^WEB_PORT=' .env 2>/dev/null | cut -d= -f2 || echo 8080; }
running() { [ -n "$(docker compose ps -q website 2>/dev/null)" ]; }

case "${1:-help}" in
  status)
    docker compose ps
    if curl -fsS "http://127.0.0.1:$(port)/api/me" >/dev/null 2>&1; then say "Website is up on port $(port)."; else die "Website isn't answering on port $(port)."; fi
    ;;
  logs)
    docker compose logs -f --tail=100
    ;;
  restart)
    docker compose up -d --force-recreate
    say "Restarted (settings from .env reloaded)."
    ;;
  update)
    say "Getting the latest code..."
    git pull --ff-only
    "$0" backup --quiet || true
    docker compose up -d --build
    say "Updated. Your accounts and pages were kept."
    ;;
  backup)
    running || die "The website isn't running."
    mkdir -p backups
    # Copy the database safely while it's running, then pack it with the pics.
    docker compose exec -T website python -c "import sqlite3; s=sqlite3.connect('/data/site.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d); d.close()"
    FILE="website-$(date +%F-%H%M).tgz"
    docker run --rm -v "$VOLUME":/data -v "$DIR/backups":/backup alpine \
      sh -c "tar czf /backup/$FILE -C /data --exclude=site.db --exclude=site.db-wal --exclude=site.db-shm . && rm /data/backup.db"
    ls -1t backups/website-*.tgz | tail -n +15 | xargs -r rm --
    [ "${2:-}" = "--quiet" ] || say "Backed up to backups/$FILE"
    ;;
  restore)
    F="${2:-}"; [ -f "$F" ] || die "Usage: ./site.sh restore backups/website-XXXX.tgz"
    read -rp "This replaces ALL accounts, pages and pics with the backup. Type yes to continue: " ok
    [ "$ok" = "yes" ] || exit 1
    "$0" backup --quiet || true
    docker compose stop website
    docker run --rm -v "$VOLUME":/data -v "$(readlink -f "$F")":/restore.tgz:ro alpine \
      sh -c "rm -rf /data/* && tar xzf /restore.tgz -C /data && mv /data/backup.db /data/site.db && chown -R 10001 /data"
    docker compose start website
    say "Restored from $F"
    ;;
  export-pages)
    running || die "The website isn't running."
    OUT="${2:-pages-$(date +%F-%H%M).json}"
    docker compose exec -T website python -m app.manage export-content > "$OUT"
    say "Saved every page to $OUT"
    ;;
  import-pages)
    F="${2:-}"; [ -f "$F" ] || die "Usage: ./site.sh import-pages pages.json   (try pages/site-content.json for the starter pages)"
    running || die "The website isn't running."
    docker compose exec -T website python -m app.manage import-content < "$F"
    say "Old version is still in History in the Site Manager if you want it back."
    ;;
  admin)
    [ -n "${2:-}" ] || die "Usage: ./site.sh admin USERNAME"
    docker compose exec website python -m app.manage create-admin "$2"
    ;;
  reset-password)
    [ -n "${2:-}" ] || die "Usage: ./site.sh reset-password USERNAME"
    docker compose exec website python -m app.manage reset-password "$2"
    ;;
  *)
    cat <<EOF
Usage: ./site.sh <command>

  status                 Is the website running?
  logs                   Watch the website's log (Ctrl+C to stop)
  restart                Restart (use after editing .env)
  update                 Pull the latest code from GitHub, back up, rebuild, restart
  backup                 Back up accounts, pages, blog and pics to ./backups (keeps 14)
  restore FILE           Put a backup back (replaces everything)
  export-pages [FILE]    Save every page (tabs, sections, settings) to a JSON file
  import-pages FILE      Upload every page from a JSON file and publish it
  admin USERNAME         Make an admin account (or make an existing user an admin)
  reset-password USER    Set a new password for someone
EOF
    ;;
esac
