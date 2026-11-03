"""Admin commands. Run inside the container, for example:

    docker compose exec website python -m app.manage create-admin Raiden
    docker compose exec website python -m app.manage reset-password SomeUser
"""
import getpass
import json
import sys

from . import content as C
from .main import USER_RE, conn, now, ph


def ask_password():
    while True:
        pw = getpass.getpass("New password: ")
        if len(pw) < 12:
            print("Use at least 12 characters for this one.")
            continue
        if pw != getpass.getpass("Type it again: "):
            print("Those didn't match, try again.")
            continue
        return pw


def create_admin(name):
    if not USER_RE.fullmatch(name):
        sys.exit("Usernames are 3-20 letters, numbers or underscores.")
    with conn() as c:
        r = c.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()
        if r:
            c.execute("UPDATE users SET is_admin=1, banned=0 WHERE id=?", (r["id"],))
            print(f"{name} is now an admin.")
            return
    pw = ask_password()
    with conn() as c:
        c.execute("INSERT INTO users(username, pw_hash, is_admin, created_at) VALUES(?,?,1,?)",
                  (name, ph.hash(pw), now()))
    print(f"Created admin account {name}.")


def reset_password(name):
    with conn() as c:
        if not c.execute("SELECT 1 FROM users WHERE username=?", (name,)).fetchone():
            sys.exit("No user with that name.")
    pw = ask_password()
    with conn() as c:
        uid = c.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()["id"]
        c.execute("UPDATE users SET pw_hash=? WHERE id=?", (ph.hash(pw), uid))
        c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    print(f"Password reset for {name}. They've been logged out everywhere.")


def remove_admin(name):
    with conn() as c:
        c.execute("UPDATE users SET is_admin=0 WHERE username=?", (name,))
    print(f"{name} is no longer an admin.")


def has_admin():
    with conn() as c:
        found = c.execute("SELECT 1 FROM users WHERE is_admin=1").fetchone()
    sys.exit(0 if found else 1)


def export_content():
    """Print every page (tabs, sections, settings) as JSON."""
    with conn() as c:
        data = c.execute("SELECT data FROM content ORDER BY id DESC LIMIT 1").fetchone()["data"]
    print(json.dumps(json.loads(data), indent=2, ensure_ascii=False))


def import_content():
    """Read pages JSON from stdin, check it, and publish it as a new version (old one stays in History)."""
    try:
        raw = json.loads(sys.stdin.read())
        clean = C.validate(raw.get("content", raw) if isinstance(raw, dict) else raw)
    except json.JSONDecodeError as e:
        sys.exit(f"That file isn't valid JSON: {e}")
    except C.ContentError as e:
        sys.exit(f"Problem in the pages file: {e}")
    with conn() as c:
        c.execute("INSERT INTO content(data, saved_at, saved_by) VALUES(?,?,?)", (json.dumps(clean), now(), "import"))
    print(f"Imported {len(clean['tabs'])} tabs. They're live now.")


COMMANDS = {"create-admin": create_admin, "reset-password": reset_password, "remove-admin": remove_admin}
NO_ARG = {"has-admin": has_admin, "export-content": export_content, "import-content": import_content}

if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] in NO_ARG:
        NO_ARG[sys.argv[1]]()
    elif len(sys.argv) == 3 and sys.argv[1] in COMMANDS:
        COMMANDS[sys.argv[1]](sys.argv[2])
    else:
        sys.exit("Usage: python -m app.manage [create-admin|reset-password|remove-admin] USERNAME\n"
                 "       python -m app.manage [has-admin|export-content|import-content]")
