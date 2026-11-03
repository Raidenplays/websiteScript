"""ItsRaiden website server.

Serves the static pages in /static and a small JSON API for accounts,
the shoutbox, the poll, the visitor counter, pics and the YouTube feed.
"""
import hashlib
import json
import io
import os
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from contextlib import contextmanager
from pathlib import Path
from typing import List
from urllib.parse import urlparse

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from defusedxml import ElementTree as ET
from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from PIL import Image, ImageOps
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from . import content as C

# ---------------------------------------------------------------- settings
BASE = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("DATA_DIR", BASE / "data"))
STATIC = Path(os.environ.get("STATIC_DIR", BASE / "static"))
PICS = DATA / "pics"
DB_PATH = DATA / "site.db"

COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1") != "0"
# "__Host-" cookies can only be set over HTTPS, on this exact host, for the whole site.
COOKIE = "__Host-sid" if COOKIE_SECURE else "sid"
SESSION_SECONDS = 30 * 86400
ALLOWED_ORIGINS = {o.strip().rstrip("/") for o in os.environ.get("SITE_ORIGIN", "").split(",") if o.strip()}
CHANNEL_ID = os.environ.get("YT_CHANNEL_ID", "UCJMqGXShRihZ6F5QyrZrIcg")
MAX_UPLOAD = 10 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 40_000_000


def _https(url):
    url = (url or "").strip()
    return url if re.fullmatch(r"https://[^\s\"'<>]+", url) else ""


def _email(addr):
    addr = (addr or "").strip()
    return addr if re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", addr) else ""


PUBLIC_CONFIG = {
    "discord": _https(os.environ.get("DISCORD_INVITE")),
    "slinkgrenade": _https(os.environ.get("SLINKGRENADE_URL")),
    "github": _https(os.environ.get("GITHUB_URL")),
    "linkedin": _https(os.environ.get("LINKEDIN_URL")),
    "email": _email(os.environ.get("CONTACT_EMAIL")),
}
# Optional Cloudflare Turnstile robot check on sign-up (free: Cloudflare dashboard > Turnstile).
TURNSTILE_SITE_KEY = re.sub(r"[^A-Za-z0-9_-]", "", os.environ.get("TURNSTILE_SITE_KEY", ""))
TURNSTILE_SECRET = os.environ.get("TURNSTILE_SECRET_KEY", "").strip()
TURNSTILE_ON = bool(TURNSTILE_SITE_KEY and TURNSTILE_SECRET)

# Set TRUST_CLOUDFLARE=1 when the site sits behind a Cloudflare Tunnel, so rate limits
# see each visitor's real IP instead of the tunnel's. Only safe if the app port isn't public.
TRUST_CLOUDFLARE = os.environ.get("TRUST_CLOUDFLARE", "0") == "1"

ph = PasswordHasher()  # argon2id with safe defaults
DUMMY_HASH = ph.hash(secrets.token_hex(16))

# ---------------------------------------------------------------- database
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  pw_hash TEXT NOT NULL,
  is_admin INTEGER NOT NULL DEFAULT 0,
  banned INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS shouts(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  body TEXT NOT NULL,
  created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS polls(
  id INTEGER PRIMARY KEY,
  question TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS poll_options(
  id INTEGER PRIMARY KEY,
  poll_id INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  position INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS votes(
  poll_id INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  option_id INTEGER NOT NULL REFERENCES poll_options(id) ON DELETE CASCADE,
  PRIMARY KEY(poll_id, user_id));
CREATE TABLE IF NOT EXISTS visits(day TEXT NOT NULL, visitor TEXT NOT NULL, PRIMARY KEY(day, visitor));
CREATE TABLE IF NOT EXISTS pics(
  id INTEGER PRIMARY KEY,
  filename TEXT NOT NULL UNIQUE,
  caption TEXT NOT NULL,
  created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS content(
  id INTEGER PRIMARY KEY,
  data TEXT NOT NULL,
  saved_at INTEGER NOT NULL,
  saved_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS posts(
  id INTEGER PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  published INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL);
"""


def now():
    return int(time.time())


def _connect():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


@contextmanager
def conn():
    c = _connect()
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db():
    DATA.mkdir(parents=True, exist_ok=True)
    PICS.mkdir(parents=True, exist_ok=True)
    with conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        if not c.execute("SELECT 1 FROM meta WHERE key='visit_salt'").fetchone():
            c.execute("INSERT INTO meta VALUES('visit_salt', ?)", (secrets.token_hex(32),))
        if not c.execute("SELECT 1 FROM content").fetchone():
            c.execute("INSERT INTO content(data, saved_at, saved_by) VALUES(?,?,?)",
                      (json.dumps(C.DEFAULT), now(), "setup"))
        if not c.execute("SELECT 1 FROM polls").fetchone():
            create_poll(c, "What should the next video be?",
                        ["Haunted mineshaft", "Abandoned server", "Creepy seed you send me", "Modded survival"])


def create_poll(c, question, options):
    c.execute("UPDATE polls SET active=0")
    pid = c.execute("INSERT INTO polls(question, created_at) VALUES(?,?)", (question, now())).lastrowid
    for i, label in enumerate(options):
        c.execute("INSERT INTO poll_options(poll_id, label, position) VALUES(?,?,?)", (pid, label, i))


init_db()

# ---------------------------------------------------------------- helpers
class Limiter:
    """In-memory sliding-window rate limiter (run the server with ONE worker)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.hits = defaultdict(deque)

    def _trim(self, key, window):
        q = self.hits[key]
        cutoff = time.monotonic() - window
        while q and q[0] <= cutoff:
            q.popleft()
        return q

    def count(self, key, window):
        with self.lock:
            return len(self._trim(key, window))

    def add(self, key):
        with self.lock:
            self.hits[key].append(time.monotonic())
            if len(self.hits) > 20000:  # forget idle keys
                for k in [k for k, q in self.hits.items() if not q or q[-1] < time.monotonic() - 3600]:
                    del self.hits[k]

    def hit(self, key, limit, window):
        """Record an attempt; False if over the limit."""
        with self.lock:
            q = self._trim(key, window)
            if len(q) >= limit:
                return False
            q.append(time.monotonic())
            return True

    def clear(self, key):
        with self.lock:
            self.hits.pop(key, None)


limiter = Limiter()


def fail(status, msg):
    raise HTTPException(status, msg)


def client_ip(req: Request):
    if TRUST_CLOUDFLARE:
        cf = req.headers.get("cf-connecting-ip", "").strip()
        if cf and len(cf) <= 45:
            return cf
    return req.client.host if req.client else "unknown"


def token_hash(tok):
    return hashlib.sha256(tok.encode()).hexdigest()


def clean_text(s, maxlen):
    s = unicodedata.normalize("NFC", s or "")
    s = re.sub(r"\s+", " ", s)  # line breaks/tabs become spaces before control chars are removed
    s = "".join(ch for ch in s if not unicodedata.category(ch).startswith("C"))  # control + invisible chars
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > maxlen:
        fail(400, f"That's too long (max {maxlen} characters).")
    return s


def request_token(req: Request):
    auth = req.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return req.cookies.get(COOKIE)


def current_user(req: Request):
    tok = request_token(req)
    if not tok or len(tok) > 100:
        return None
    with conn() as c:
        r = c.execute(
            "SELECT u.id, u.username, u.is_admin, u.banned FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token_hash=? AND s.expires_at>?", (token_hash(tok), now())).fetchone()
    if not r or r["banned"]:
        return None
    return dict(r)


def need_user(req):
    u = current_user(req)
    if not u:
        fail(401, "You need to log in first.")
    return u


def need_admin(req):
    u = need_user(req)
    if not u["is_admin"]:
        fail(403, "Admins only.")
    return u


def start_session(resp: Response, c, user_id):
    tok = secrets.token_urlsafe(32)
    c.execute("DELETE FROM sessions WHERE expires_at<?", (now(),))
    c.execute("INSERT INTO sessions VALUES(?,?,?)", (token_hash(tok), user_id, now() + SESSION_SECONDS))
    resp.set_cookie(COOKIE, tok, max_age=SESSION_SECONDS, httponly=True,
                    secure=COOKIE_SECURE, samesite="lax", path="/")


def end_session_cookie(resp: Response):
    resp.delete_cookie(COOKIE, path="/", httponly=True, secure=COOKIE_SECURE, samesite="lax")


def verify_pw(pw_hash, password):
    try:
        return ph.verify(pw_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


USER_RE = re.compile(r"[A-Za-z0-9_]{3,20}")
RESERVED = {"admin", "administrator", "mod", "moderator", "staff", "system", "root",
            "raiden", "itsraiden", "itsraidenfr", "slinkgrenade"}
COMMON_PW = {"password", "password1", "password123", "12345678", "123456789", "1234567890", "11111111",
             "00000000", "qwertyui", "qwerty123", "qwertyuiop", "iloveyou", "letmein1", "abcdefgh",
             "minecraft", "minecraft1", "minecraft123", "creeper123", "herobrine", "football1"}


def check_password(pw, username):
    if not 10 <= len(pw) <= 128:
        fail(400, "Passwords have to be 10 to 128 characters.")
    if pw.lower() in COMMON_PW or username.lower() in pw.lower():
        fail(400, "That password is too easy to guess. Try something else!")


# ---------------------------------------------------------------- app
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

_TS = " https://challenges.cloudflare.com" if TURNSTILE_ON else ""
CSP = ("default-src 'self'; script-src 'self'" + _TS + "; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: https://i.ytimg.com; "
       "frame-src https://www.youtube-nocookie.com https://www.youtube.com https://discord.com" + _TS + "; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def origin_ok(req: Request):
    origin = (req.headers.get("origin") or "").rstrip("/")
    if not origin:
        return False
    if ALLOWED_ORIGINS:
        return origin in ALLOWED_ORIGINS
    return urlparse(origin).netloc == req.headers.get("host")


def https_redirect(req: Request):
    """Behind Cloudflare, send anyone who arrived over plain http:// to https://."""
    if not (TRUST_CLOUDFLARE and COOKIE_SECURE):
        return None
    proto = req.headers.get("x-forwarded-proto", "").lower()
    if proto != "http" and '"scheme":"http"' not in req.headers.get("cf-visitor", "").replace(" ", ""):
        return None
    host = (req.headers.get("host") or "").lower()
    origins = sorted(ALLOWED_ORIGINS)
    target = next((o for o in origins if urlparse(o).netloc == host), origins[0] if origins else None)
    if not target:
        return None
    path = req.url.path + ("?" + req.url.query if req.url.query else "")
    return RedirectResponse(target + path, status_code=308)


@app.middleware("http")
async def security(req: Request, call_next):
    redirect = https_redirect(req)
    if redirect:
        return redirect
    if req.method not in ("GET", "HEAD", "OPTIONS"):
        # Blocks cross-site request forgery: browsers always send Origin on POST/DELETE.
        # The desktop app uses a Bearer token instead of a cookie; browsers never attach those on their
        # own, so those requests (and the app's login, which sets no cookie) don't need the check.
        bearer = req.headers.get("authorization", "").startswith("Bearer ")
        if not bearer and req.url.path != "/api/app/login" and not origin_ok(req):
            return JSONResponse({"error": "Request blocked (bad origin)."}, 403)
        try:
            if int(req.headers.get("content-length") or 0) > MAX_UPLOAD + 100_000:
                return JSONResponse({"error": "That file is too big (max 10 MB)."}, 413)
        except ValueError:
            return JSONResponse({"error": "Bad request."}, 400)
    resp = await call_next(req)
    h = resp.headers
    h["Content-Security-Policy"] = CSP
    h["X-Content-Type-Options"] = "nosniff"
    h["Referrer-Policy"] = "strict-origin-when-cross-origin"  # YouTube embeds need this
    h["X-Frame-Options"] = "DENY"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    if COOKIE_SECURE:
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if req.url.path.startswith("/api/"):
        h["Cache-Control"] = "no-store"
    return resp


@app.exception_handler(HTTPException)
async def http_error(req: Request, exc: HTTPException):
    if req.url.path.startswith("/api/") or exc.status_code != 404:
        return JSONResponse({"error": exc.detail}, exc.status_code)
    return HTMLResponse(system_page("404", "Page Not Found", side=False), status_code=404)


@app.exception_handler(RequestValidationError)
async def bad_input(req, exc):
    return JSONResponse({"error": "Invalid input."}, 400)


# ---- public config / me
@app.get("/api/config")
def config():
    # Only what the page scripts need. The email address is NOT sent here (it's only in page links,
    # where Cloudflare's email protection can hide it from scrapers).
    return {"discord": PUBLIC_CONFIG["discord"], "slinkgrenade": PUBLIC_CONFIG["slinkgrenade"],
            "turnstile": TURNSTILE_SITE_KEY if TURNSTILE_ON else ""}


@app.get("/api/me")
def me(req: Request):
    u = current_user(req)
    return {"user": {"name": u["username"], "admin": bool(u["is_admin"])} if u else None}


# ---- accounts
class Creds(BaseModel):
    username: str
    password: str


class SignupIn(Creds):
    turnstile: str = ""


def turnstile_ok(token, ip):
    if not TURNSTILE_ON:
        return True
    if not token or len(token) > 2048:
        return False
    try:
        data = urllib.parse.urlencode({"secret": TURNSTILE_SECRET, "response": token, "remoteip": ip}).encode()
        r = urllib.request.Request("https://challenges.cloudflare.com/turnstile/v0/siteverify", data=data,
                                   headers={"User-Agent": "RaidenSite/1.0"})
        with urllib.request.urlopen(r, timeout=10) as f:
            return bool(json.loads(f.read(100_000)).get("success"))
    except Exception:
        return False


@app.post("/api/signup")
def signup(body: SignupIn, req: Request, resp: Response):
    if not limiter.hit("signup:" + client_ip(req), 10, 3600):
        fail(429, "Too many sign-ups from here. Try again in an hour.")
    if not turnstile_ok(body.turnstile, client_ip(req)):
        fail(400, "Please finish the robot check, then try again.")
    name = body.username.strip()
    if not USER_RE.fullmatch(name):
        fail(400, "Usernames are 3-20 letters, numbers or underscores.")
    if name.lower() in RESERVED:
        fail(400, "That username is taken.")
    check_password(body.password, name)
    pw_hash = ph.hash(body.password)
    with conn() as c:
        try:
            uid = c.execute("INSERT INTO users(username, pw_hash, created_at) VALUES(?,?,?)",
                            (name, pw_hash, now())).lastrowid
        except sqlite3.IntegrityError:
            fail(400, "That username is taken.")
        start_session(resp, c, uid)
    return {"ok": True}


@app.post("/api/login")
def login(body: Creds, req: Request, resp: Response):
    ip_key = "loginip:" + client_ip(req)
    name = body.username.strip()[:40]
    user_key = "loginuser:" + name.lower()
    if limiter.count(ip_key, 900) >= 20 or limiter.count(user_key, 900) >= 8:
        fail(429, "Too many tries. Wait 15 minutes and try again.")
    with conn() as c:
        r = c.execute("SELECT id, pw_hash, banned FROM users WHERE username=?", (name,)).fetchone()
        # Always run a hash check so response time doesn't reveal whether the username exists.
        ok = verify_pw(r["pw_hash"] if r else DUMMY_HASH, body.password[:128]) and r is not None
        if not ok:
            limiter.add(ip_key)
            limiter.add(user_key)
            fail(401, "Wrong username or password.")
        if r["banned"]:
            fail(403, "This account has been banned.")
        if ph.check_needs_rehash(r["pw_hash"]):
            c.execute("UPDATE users SET pw_hash=? WHERE id=?", (ph.hash(body.password), r["id"]))
        start_session(resp, c, r["id"])
    limiter.clear(user_key)
    return {"ok": True}


@app.post("/api/logout")
def logout(req: Request, resp: Response):
    tok = request_token(req)
    if tok:
        with conn() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(tok),))
    end_session_cookie(resp)
    return {"ok": True}


class PasswordChange(BaseModel):
    current: str
    new: str


def check_current_pw(c, u, password):
    if not limiter.hit("acct:%d" % u["id"], 10, 900):
        fail(429, "Too many tries. Wait 15 minutes and try again.")
    r = c.execute("SELECT pw_hash FROM users WHERE id=?", (u["id"],)).fetchone()
    if not verify_pw(r["pw_hash"], password[:128]):
        fail(401, "Your current password is wrong.")


@app.post("/api/account/password")
def change_password(body: PasswordChange, req: Request, resp: Response):
    u = need_user(req)
    with conn() as c:
        check_current_pw(c, u, body.current)
        check_password(body.new, u["username"])
        c.execute("UPDATE users SET pw_hash=? WHERE id=?", (ph.hash(body.new), u["id"]))
        c.execute("DELETE FROM sessions WHERE user_id=?", (u["id"],))  # log out everywhere else
        start_session(resp, c, u["id"])
    return {"ok": True}


class PasswordOnly(BaseModel):
    password: str


@app.post("/api/account/delete")
def delete_account(body: PasswordOnly, req: Request, resp: Response):
    u = need_user(req)
    with conn() as c:
        check_current_pw(c, u, body.password)
        c.execute("DELETE FROM users WHERE id=?", (u["id"],))  # shouts, votes, sessions go with it
    end_session_cookie(resp)
    return {"ok": True}


# ---- shoutbox
class Shout(BaseModel):
    body: str


@app.get("/api/shouts")
def get_shouts(req: Request):
    u = current_user(req)
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM (SELECT s.id, s.body, s.created_at, s.user_id, u.username FROM shouts s "
            "JOIN users u ON u.id=s.user_id WHERE u.banned=0 ORDER BY s.id DESC LIMIT 50) ORDER BY id").fetchall()
    return {"shouts": [{"id": r["id"], "user": r["username"], "body": r["body"], "at": r["created_at"],
                        "can_delete": bool(u and (u["is_admin"] or u["id"] == r["user_id"]))} for r in rows]}


@app.post("/api/shouts")
def post_shout(body: Shout, req: Request):
    u = need_user(req)
    text = clean_text(body.body, 200)
    if not text:
        fail(400, "Say something first!")
    if limiter.count("shoutmin:%d" % u["id"], 10) >= 1 or limiter.count("shouthr:%d" % u["id"], 3600) >= 30:
        fail(429, "Slow down! Wait a few seconds before shouting again.")
    limiter.add("shoutmin:%d" % u["id"])
    limiter.add("shouthr:%d" % u["id"])
    with conn() as c:
        c.execute("INSERT INTO shouts(user_id, body, created_at) VALUES(?,?,?)", (u["id"], text, now()))
        c.execute("DELETE FROM shouts WHERE id NOT IN (SELECT id FROM shouts ORDER BY id DESC LIMIT 1000)")
    return {"ok": True}


@app.delete("/api/shouts/{shout_id}")
def delete_shout(shout_id: int, req: Request):
    u = need_user(req)
    with conn() as c:
        if u["is_admin"]:
            c.execute("DELETE FROM shouts WHERE id=?", (shout_id,))
        else:
            c.execute("DELETE FROM shouts WHERE id=? AND user_id=?", (shout_id, u["id"]))
    return {"ok": True}


# ---- poll
def poll_data(c, u):
    p = c.execute("SELECT id, question FROM polls WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone()
    if not p:
        return None
    opts = c.execute(
        "SELECT o.id, o.label, (SELECT COUNT(*) FROM votes v WHERE v.option_id=o.id) AS votes "
        "FROM poll_options o WHERE o.poll_id=? ORDER BY o.position", (p["id"],)).fetchall()
    mine = None
    if u:
        r = c.execute("SELECT option_id FROM votes WHERE poll_id=? AND user_id=?", (p["id"], u["id"])).fetchone()
        mine = r["option_id"] if r else None
    return {"id": p["id"], "question": p["question"], "my_vote": mine,
            "options": [dict(o) for o in opts]}


@app.get("/api/poll")
def get_poll(req: Request):
    u = current_user(req)
    with conn() as c:
        return {"poll": poll_data(c, u)}


class Vote(BaseModel):
    option_id: int


@app.post("/api/poll/vote")
def vote(body: Vote, req: Request):
    u = need_user(req)
    with conn() as c:
        r = c.execute("SELECT o.poll_id FROM poll_options o JOIN polls p ON p.id=o.poll_id "
                      "WHERE o.id=? AND p.active=1", (body.option_id,)).fetchone()
        if not r:
            fail(400, "That poll is closed.")
        c.execute("INSERT OR IGNORE INTO votes VALUES(?,?,?)", (r["poll_id"], u["id"], body.option_id))
        return {"poll": poll_data(c, u)}


# ---- visitor counter (unique visitors per day; IPs are never stored, only a salted hash)
@app.post("/api/hit")
def hit(req: Request):
    day = time.strftime("%Y-%m-%d", time.gmtime())
    with conn() as c:
        salt = c.execute("SELECT value FROM meta WHERE key='visit_salt'").fetchone()["value"]
        who = hashlib.sha256(f"{salt}|{day}|{client_ip(req)}|{req.headers.get('user-agent', '')[:200]}"
                             .encode()).hexdigest()
        c.execute("INSERT OR IGNORE INTO visits VALUES(?,?)", (day, who))
        total = c.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
    return {"visitors": total}


# ---- YouTube feed (fetched by the server, cached 15 minutes)
_feed = {"t": 0.0, "videos": []}
_feed_lock = threading.Lock()
ATOM = "{http://www.w3.org/2005/Atom}"
YT = "{http://www.youtube.com/xml/schemas/2015}"


def parse_feed(raw):
    root = ET.fromstring(raw)
    out = []
    for e in root.findall(ATOM + "entry"):
        vid = e.findtext(YT + "videoId") or ""
        if re.fullmatch(r"[\w-]{11}", vid):
            out.append({"id": vid, "title": (e.findtext(ATOM + "title") or "")[:200],
                        "published": (e.findtext(ATOM + "published") or "")[:40]})
    return out


@app.get("/api/videos")
def videos():
    with _feed_lock:
        if time.time() - _feed["t"] > 900:
            try:
                url = "https://www.youtube.com/feeds/videos.xml?channel_id=" + CHANNEL_ID
                r = urllib.request.Request(url, headers={"User-Agent": "ItsRaidenSite/1.0"})
                with urllib.request.urlopen(r, timeout=10) as f:
                    _feed["videos"] = parse_feed(f.read(3_000_000))
                _feed["t"] = time.time()
            except Exception:
                _feed["t"] = time.time() - 780  # try again in 2 minutes
        return {"videos": _feed["videos"]}


# ---- pics
@app.get("/api/pics")
def list_pics():
    with conn() as c:
        rows = c.execute("SELECT id, filename, caption FROM pics ORDER BY id DESC").fetchall()
    return {"pics": [{"id": r["id"], "url": "/pics/" + r["filename"], "caption": r["caption"]} for r in rows]}


@app.get("/pics/{name}")
def get_pic(name: str):
    if not re.fullmatch(r"[a-f0-9]{32}\.webp", name) or not (PICS / name).is_file():
        fail(404, "Not found")
    return FileResponse(PICS / name, media_type="image/webp",
                        headers={"Cache-Control": "public, max-age=604800, immutable"})


# ---- admin
@app.post("/api/admin/pics")
async def upload_pic(req: Request, file: UploadFile = File(...), caption: str = Form("")):
    need_admin(req)
    cap = clean_text(caption, 60)
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        fail(413, "That file is too big (max 10 MB).")
    try:
        Image.open(io.BytesIO(data)).verify()
        im = Image.open(io.BytesIO(data))
        if im.format not in ("PNG", "JPEG", "GIF", "WEBP"):
            fail(400, "Only PNG, JPG, GIF or WEBP images.")
        im.load()
        im = ImageOps.exif_transpose(im)
        im.thumbnail((1920, 1920))
        im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
        out = io.BytesIO()
        im.save(out, "WEBP", quality=85)  # re-encoding strips metadata and anything hidden in the file
    except HTTPException:
        raise
    except Exception:
        fail(400, "That doesn't look like a valid image.")
    name = secrets.token_hex(16) + ".webp"
    (PICS / name).write_bytes(out.getvalue())
    with conn() as c:
        c.execute("INSERT INTO pics(filename, caption, created_at) VALUES(?,?,?)", (name, cap, now()))
    return {"ok": True}


@app.delete("/api/admin/pics/{pic_id}")
def delete_pic(pic_id: int, req: Request):
    need_admin(req)
    with conn() as c:
        r = c.execute("SELECT filename FROM pics WHERE id=?", (pic_id,)).fetchone()
        if r:
            c.execute("DELETE FROM pics WHERE id=?", (pic_id,))
            (PICS / r["filename"]).unlink(missing_ok=True)
    return {"ok": True}


class NewPoll(BaseModel):
    question: str
    options: List[str]


@app.post("/api/admin/poll")
def new_poll(body: NewPoll, req: Request):
    need_admin(req)
    q = clean_text(body.question, 120)
    opts = [o for o in (clean_text(x, 60) for x in body.options[:6]) if o]
    if not q or len(opts) < 2:
        fail(400, "A poll needs a question and at least 2 options.")
    with conn() as c:
        create_poll(c, q, opts)
    return {"ok": True}


@app.get("/api/admin/users")
def list_users(req: Request):
    need_admin(req)
    with conn() as c:
        rows = c.execute("SELECT id, username, is_admin, banned, created_at FROM users "
                         "ORDER BY id DESC LIMIT 500").fetchall()
    return {"users": [dict(r) for r in rows]}


class Ban(BaseModel):
    banned: bool


@app.post("/api/admin/users/{user_id}/ban")
def ban_user(user_id: int, body: Ban, req: Request):
    need_admin(req)
    with conn() as c:
        r = c.execute("SELECT is_admin FROM users WHERE id=?", (user_id,)).fetchone()
        if not r:
            fail(404, "No such user.")
        if r["is_admin"]:
            fail(400, "You can't ban an admin.")
        c.execute("UPDATE users SET banned=? WHERE id=?", (int(body.banned), user_id))
        if body.banned:
            c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    return {"ok": True}


# ---- desktop app login (admins only; returns a token instead of setting a cookie)
@app.post("/api/app/login")
def app_login(body: Creds, req: Request):
    ip_key = "loginip:" + client_ip(req)
    name = body.username.strip()[:40]
    user_key = "loginuser:" + name.lower()
    if limiter.count(ip_key, 900) >= 20 or limiter.count(user_key, 900) >= 8:
        fail(429, "Too many tries. Wait 15 minutes and try again.")
    with conn() as c:
        r = c.execute("SELECT id, pw_hash, banned, is_admin FROM users WHERE username=?", (name,)).fetchone()
        ok = verify_pw(r["pw_hash"] if r else DUMMY_HASH, body.password[:128]) and r is not None
        if not ok:
            limiter.add(ip_key)
            limiter.add(user_key)
            fail(401, "Wrong username or password.")
        if r["banned"] or not r["is_admin"]:
            fail(403, "Only admin accounts can use the Site Manager.")
        tok = secrets.token_urlsafe(32)
        c.execute("DELETE FROM sessions WHERE expires_at<?", (now(),))
        c.execute("INSERT INTO sessions VALUES(?,?,?)", (token_hash(tok), r["id"], now() + SESSION_SECONDS))
    limiter.clear(user_key)
    return {"token": tok, "name": name}


# ---- site content (tabs + sections)
_content_cache = {"id": None, "data": None}


def get_content():
    with conn() as c:
        r = c.execute("SELECT id, data FROM content ORDER BY id DESC LIMIT 1").fetchone()
    if _content_cache["id"] != r["id"]:
        _content_cache.update(id=r["id"], data=json.loads(r["data"]))
    return _content_cache["id"], _content_cache["data"]


def render_cfg():
    return {**PUBLIC_CONFIG, "youtube": "https://www.youtube.com/@itsraidenfr",
            "coffee": "https://buymeacoffee.com/itsraiden"}


def published_posts():
    with conn() as c:
        rows = c.execute("SELECT slug, title, body, created_at FROM posts WHERE published=1 "
                         "ORDER BY created_at DESC LIMIT 100").fetchall()
    return [{"slug": r["slug"], "title": r["title"], "body": r["body"],
             "date": time.strftime("%B %d, %Y", time.localtime(r["created_at"])).replace(" 0", " ")} for r in rows]


def page_ctx():
    return {"channel": CHANNEL_ID, "posts": published_posts()}


@app.get("/api/admin/content")
def admin_get_content(req: Request):
    need_admin(req)
    cid, data = get_content()
    return {"version": cid, "content": data,
            "types": sorted(C.SECTION_TYPES), "icon_colors": sorted(C.ICON_COLORS), "badge_colors": sorted(C.BADGE_COLORS)}


class ContentSave(BaseModel):
    version: int
    content: dict


@app.put("/api/admin/content")
def admin_save_content(body: ContentSave, req: Request):
    u = need_admin(req)
    try:
        clean = C.validate(body.content)
    except C.ContentError as e:
        fail(400, str(e))
    with conn() as c:
        latest = c.execute("SELECT id FROM content ORDER BY id DESC LIMIT 1").fetchone()["id"]
        if latest != body.version:
            fail(409, "Someone else saved changes since you loaded. Reload to get the latest version.")
        cid = c.execute("INSERT INTO content(data, saved_at, saved_by) VALUES(?,?,?)",
                        (json.dumps(clean), now(), u["username"])).lastrowid
        c.execute("DELETE FROM content WHERE id NOT IN (SELECT id FROM content ORDER BY id DESC LIMIT 50)")
    return {"ok": True, "version": cid, "content": clean}


@app.get("/api/admin/content/history")
def admin_history(req: Request):
    need_admin(req)
    with conn() as c:
        rows = c.execute("SELECT id, saved_at, saved_by FROM content ORDER BY id DESC").fetchall()
    return {"history": [dict(r) for r in rows]}


@app.post("/api/admin/content/history/{cid}/restore")
def admin_restore(cid: int, req: Request):
    u = need_admin(req)
    with conn() as c:
        r = c.execute("SELECT data FROM content WHERE id=?", (cid,)).fetchone()
        if not r:
            fail(404, "That version doesn't exist anymore.")
        new = c.execute("INSERT INTO content(data, saved_at, saved_by) VALUES(?,?,?)",
                        (r["data"], now(), u["username"] + " (restored #%d)" % cid)).lastrowid
    return {"ok": True, "version": new}


@app.post("/api/admin/content/check")
def admin_check_content(body: ContentSave, req: Request):
    """Check content for mistakes without saving it."""
    need_admin(req)
    try:
        clean = C.validate(body.content)
    except C.ContentError as e:
        fail(400, str(e))
    return {"ok": True}


# ---- blog
class PostIn(BaseModel):
    title: str
    body: str
    published: bool = False


def _slugify(c, title, post_id=None):
    base = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()).strip("-")[:60] or "post"
    slug, n = base, 2
    while c.execute("SELECT 1 FROM posts WHERE slug=? AND id IS NOT ?", (slug, post_id)).fetchone():
        slug, n = "%s-%d" % (base, n), n + 1
    return slug


def _check_post(body):
    title = clean_text(body.title, 120)
    text = body.body.replace("\r\n", "\n")
    text = "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)
    if not title:
        fail(400, "Your post needs a title.")
    if len(text) > 50000:
        fail(400, "That post is too long (max 50,000 characters).")
    return title, text


@app.get("/api/admin/posts")
def admin_posts(req: Request):
    need_admin(req)
    with conn() as c:
        rows = c.execute("SELECT id, slug, title, body, published, created_at, updated_at FROM posts ORDER BY created_at DESC").fetchall()
    return {"posts": [dict(r) for r in rows]}


@app.post("/api/admin/posts")
def admin_new_post(body: PostIn, req: Request):
    need_admin(req)
    title, text = _check_post(body)
    with conn() as c:
        pid = c.execute("INSERT INTO posts(slug, title, body, published, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                        (_slugify(c, title), title, text, int(body.published), now(), now())).lastrowid
    return {"ok": True, "id": pid}


@app.put("/api/admin/posts/{post_id}")
def admin_edit_post(post_id: int, body: PostIn, req: Request):
    need_admin(req)
    title, text = _check_post(body)
    with conn() as c:
        r = c.execute("SELECT published FROM posts WHERE id=?", (post_id,)).fetchone()
        if not r:
            fail(404, "That post doesn't exist.")
        # first time a draft is published, its date becomes the publish date
        extra = ", created_at=%d" % now() if body.published and not r["published"] else ""
        c.execute("UPDATE posts SET slug=?, title=?, body=?, published=?, updated_at=?%s WHERE id=?" % extra,
                  (_slugify(c, title, post_id), title, text, int(body.published), now(), post_id))
    return {"ok": True}


@app.delete("/api/admin/posts/{post_id}")
def admin_delete_post(post_id: int, req: Request):
    need_admin(req)
    with conn() as c:
        c.execute("DELETE FROM posts WHERE id=?", (post_id,))
    return {"ok": True}


# ---- more user management
class AdminFlag(BaseModel):
    admin: bool


@app.post("/api/admin/users/{user_id}/admin")
def set_admin(user_id: int, body: AdminFlag, req: Request):
    u = need_admin(req)
    if user_id == u["id"]:
        fail(400, "You can't change your own admin status.")
    with conn() as c:
        if not c.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
            fail(404, "No such user.")
        c.execute("UPDATE users SET is_admin=?, banned=CASE WHEN ? THEN 0 ELSE banned END WHERE id=?",
                  (int(body.admin), int(body.admin), user_id))
        c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    return {"ok": True}


class NewPassword(BaseModel):
    password: str


@app.post("/api/admin/users/{user_id}/password")
def admin_reset_password(user_id: int, body: NewPassword, req: Request):
    u = need_admin(req)
    with conn() as c:
        r = c.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
        if not r:
            fail(404, "No such user.")
        check_password(body.password, r["username"])
        c.execute("UPDATE users SET pw_hash=? WHERE id=?", (ph.hash(body.password), user_id))
        c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    return {"ok": True}


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: int, req: Request):
    u = need_admin(req)
    with conn() as c:
        r = c.execute("SELECT is_admin FROM users WHERE id=?", (user_id,)).fetchone()
        if not r:
            fail(404, "No such user.")
        if r["is_admin"]:
            fail(400, "Remove their admin status before deleting an admin.")
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
    return {"ok": True}


# ---- pages
def system_page(name, title, side=True):
    _, data = get_content()
    side_html = '      <div style="text-align:center;font-weight:bold">You are visitor number:<div id="counter"></div></div>\n'
    return C.render_page(data, render_cfg(), page_ctx(), "", C.SYSTEM_BODIES[name], side_html if side else "",
                         "%s :: %s" % (title, data["site"]["page_title"]), robots=True)


def html_page(s):
    return HTMLResponse(s, headers={"Cache-Control": "no-cache"})


@app.get("/style.css")
def style_css():
    return FileResponse(STATIC / "style.css", media_type="text/css", headers={"Cache-Control": "no-cache"})


@app.get("/site.js")
def site_js():
    return FileResponse(STATIC / "site.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/.well-known/security.txt")
def security_txt():
    contact = ("mailto:" + PUBLIC_CONFIG["email"]) if PUBLIC_CONFIG["email"] else (PUBLIC_CONFIG["linkedin"] or PUBLIC_CONFIG["discord"])
    if not contact:
        fail(404, "Not found")
    expires = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime(time.time() + 300 * 86400))
    origin = sorted(ALLOWED_ORIGINS)[0] if ALLOWED_ORIGINS else ""
    body = f"Contact: {contact}\nExpires: {expires}\nPreferred-Languages: en\n" + (f"Canonical: {origin}/.well-known/security.txt\n" if origin else "")
    return Response(body, media_type="text/plain")


@app.get("/robots.txt")
def robots():
    return FileResponse(STATIC / "robots.txt", media_type="text/plain")


@app.get("/signup")
def signup_page():
    return html_page(system_page("signup", "Sign Up"))


@app.get("/account")
def account_page():
    return html_page(system_page("account", "My Account"))


@app.get("/admin")
def admin_page():
    return html_page(system_page("admin", "Admin", side=False))


@app.get("/blog-post/{slug}")
def blog_post(slug: str):
    post = next((p for p in published_posts() if p["slug"] == slug), None)
    if not post:
        fail(404, "Not found")
    _, data = get_content()
    return html_page(C.render_post(data, render_cfg(), page_ctx(), post))


@app.get("/")
def home():
    _, data = get_content()
    return html_page(C.render_page(data, render_cfg(), page_ctx(), "home"))


@app.get("/{slug}")
def tab_page(slug: str):
    if slug.endswith(".html"):  # old links like /videos.html
        base = slug[:-5]
        return RedirectResponse("/" if base == "index" else "/" + base, status_code=301)
    _, data = get_content()
    if slug == "home" or not any(t["slug"] == slug for t in data["tabs"]):
        fail(404, "Not found")
    return html_page(C.render_page(data, render_cfg(), page_ctx(), slug))
