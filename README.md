# raidenbrundin.com

My website: a professional homepage (education, skills, homelab, Matcha Music), a blog, and the fun stuff (videos, pics, shoutbox, polls) in a 2009 web style.
It's a small Python server (FastAPI + SQLite) running in Docker. Everything is edited with the **Raiden Site Manager** Windows app.

## Install on the server (one time)

SSH into the server, then:

```bash
git clone https://github.com/Raidenplays/websiteScript.git
cd websiteScript
sudo ./install.sh        # or as root: ./install.sh
```

The installer:
1. Installs Docker if it's missing.
2. Asks for your settings (site address, email, links) and saves them in `.env`.
3. Builds and starts the site, which creates the database with all the starter pages.
4. Makes your admin account.
5. Sets up nightly backups.
6. Finds your Cloudflare Tunnel and tells you what to point it at.

It's safe to run again any time; it keeps your settings, accounts and pages.

## Updating

```bash
cd websiteScript
./site.sh update         # pulls from GitHub, backs up, rebuilds, restarts
```

## Every page in one file

```bash
./site.sh export-pages my-pages.json     # save every tab, section and setting
./site.sh import-pages my-pages.json     # upload every page from that file and publish it
./site.sh import-pages pages/site-content.json   # reset to the starter pages
```

Importing keeps the old version in History, so it can be undone from the Site Manager.

Run `./site.sh help` for everything else (status, logs, backup, restore, admin, reset-password).

## What's in here

| Path | What it is |
| --- | --- |
| `app/main.py` | The server: accounts, shoutbox, poll, visitor counter, pics, YouTube feed |
| `app/manage.py` | Admin commands (make an admin, reset a password) |
| `app/content.py` | The default pages, and how edited content is checked and turned into HTML |
| `static/` | `style.css` and `site.js` |
| `Dockerfile`, `docker-compose.yml` | Runs it all in Docker |
| `install.sh` | One-time setup (run over SSH) |
| `site.sh` | Day-to-day commands: update, backup, restore, export/import pages... |
| `pages/site-content.json` | The starter pages |
| `manager-app/` | Source code for the Raiden Site Manager Windows app |
| `.env.example` | Settings (copy to `.env`) |

## Manual setup (if you don't use install.sh)

1. Copy this folder to the server, for example `/opt/raiden-website`.
2. Make your settings file and fill it in:
   ```bash
   cp .env.example .env
   nano .env
   ```
3. Start it:
   ```bash
   docker compose up -d --build
   ```
   It now runs on `http://localhost:8080`, but only that machine can reach it.
4. Make your admin account. It asks for a password, which needs at least 12 characters:
   ```bash
   docker compose exec website python -m app.manage create-admin Raiden
   ```
5. Point your Cloudflare Tunnel at `http://localhost:8080` for `raidenbrundin.com`, in place of whatever it serves now.
   - If `cloudflared` runs **in Docker**, it can't reach `localhost` on the host. Either run it with `network_mode: host`, or put both containers on the same Docker network and use `http://raiden-website:8080`.
6. Open the site, log in at the top with your admin account, and click **Admin**.

## Editing the site: Raiden Site Manager (Windows app)

Everything on the site (tabs, sections, text, projects, links, blog posts) is stored on the server and edited from the **Raiden Site Manager** app:

1. Unzip `Raiden-Site-Manager-win64.zip` (or build it yourself from `manager-app/`) anywhere, for example `C:\Program Files\Raiden Site Manager`, and run `Raiden Site Manager.exe`.
2. Log in with your site address (`raidenbrundin.com`) and your **admin** account. Normal accounts can't use the app.
3. **Pages & Sections:** add, rename, reorder, hide or delete tabs; add, edit, reorder or delete the boxes on each page.
   Click **Save & publish** to make it live.
4. **Blog:** write posts and save them as drafts or publish them. Each post gets its own link (`/blog-post/...`).
5. **History:** every save is kept (last 50), so you can undo by restoring an old version.
6. **Pics, Poll, Shoutbox, Users:** upload pictures, start polls, delete shouts, and ban, delete, promote or reset passwords for accounts.

Windows SmartScreen may warn the first time because the app isn't code-signed. Click **More info**, then **Run anyway**.

## Day to day

- **Upload pics / start a new poll / ban someone:** use the Site Manager app (or the **Admin** page on the site).
- **Delete a shout:** click the red × next to it in the shoutbox (admins see it on every shout).
- **Someone forgot their password:** there's no email on accounts, so reset it for them:
  `docker compose exec website python -m app.manage reset-password TheirName`
- **Change a link** (email, LinkedIn, Discord…): edit `.env`, then run `docker compose up -d`.
- **Update after changing code:** `docker compose up -d --build`. Your accounts and pics are kept in the `website-data` volume.

## Backups

Accounts, pages, blog posts and pics live in the `raiden-website_website-data` Docker volume.
`./site.sh backup` saves a copy to `backups/` (nightly if you said yes in the installer, keeping the last 14).
`./site.sh restore backups/website-XXXX.tgz` puts one back.

## Security

- **Passwords** are hashed with Argon2id and never stored as text. Login checks take the same time whether the username exists or not.
- **Sessions** are random tokens in an `HttpOnly`, `Secure`, `SameSite=Lax`, `__Host-` cookie. The database only keeps a hash of each token. Changing your password logs you out everywhere else.
- **Forged requests (CSRF):** every change request has to come from the site itself (`Origin` check).
- **Rate limits:**
  - Logins: 8 wrong tries per account or 20 per IP, every 15 minutes
  - Sign-ups: 10 per IP per hour
  - Shouts: 1 every 10 seconds
- **Injected code (XSS):** everything people type is shown as plain text. A strict Content-Security-Policy also blocks any script that isn't `site.js`.
- **Uploads:** admin only, max 10 MB. Every image is checked and re-saved as WebP, which strips hidden data and metadata.
- **Edited content:** checked by the server before saving. Every bit of text is escaped, and only `https://`, site pages, email and `@settings` links are allowed.
- **Desktop app:** admin-only, and uses a token instead of a cookie. The token is stored encrypted with Windows' own protection when you tick "Keep me logged in". Logging out kills it on the server too.
- **Container:** runs as a non-root user with a read-only filesystem and no extra privileges, and the port only listens on localhost.
- **Visitor counter:** never stores anyone's IP, only a salted hash that changes every day.

Keep `COOKIE_SECURE=1` in real use. Don't port-forward 8080 on the router; the tunnel is the only way in.
