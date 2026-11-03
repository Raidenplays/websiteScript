"""Site content: the editable tabs/sections, how they're checked, and how they turn into HTML.

Everything the admin app saves goes through validate() and every piece of text is
HTML-escaped when rendered, so content can't inject scripts into the site.
"""
import copy
import html
import json
import re
from pathlib import Path

esc = html.escape

COLORS = {"green", "orange", "black"}
ICON_COLORS = {
    "green": "linear-gradient(135deg,#2d6e1a,#0d2a06)",
    "lime": "linear-gradient(135deg,#8fbf5a,#3f6b1f)",
    "blue": "linear-gradient(135deg,#1d5fa8,#0b2a4d)",
    "orange": "linear-gradient(135deg,#ff9a1a,#a34c00)",
    "purple": "linear-gradient(135deg,#7a4fd0,#2a1060)",
    "red": "linear-gradient(135deg,#d22,#600)",
    "gray": "linear-gradient(135deg,#555,#111)",
    "brown": "linear-gradient(135deg,#a0682e,#4b2e10)",
}
BADGE_COLORS = {
    "red": "linear-gradient(#c00,#600)", "orange": "linear-gradient(#f80,#930)",
    "blue": "linear-gradient(#67f,#336)", "yellow": "linear-gradient(#fd0,#c90)",
    "green": "linear-gradient(#5b2,#240)", "gray": "linear-gradient(#555,#000)",
}
SECTION_TYPES = {"text", "items", "links", "player", "videos", "pics", "marquee", "discord",
                 "blog", "poll", "shoutbox", "counter"}
SINGLE_USE = {"player", "videos", "pics", "poll", "shoutbox", "counter", "blog"}
LINK_STYLES = {"list", "buttons", "boxes", "badges"}
LINK_KEYS = {"email", "linkedin", "github", "discord", "slinkgrenade", "youtube", "coffee"}
RESERVED_SLUGS = {"api", "files", "signup", "account", "admin", "blog-post", "style.css", "site.js",
                  "robots.txt", "404", "static", "login", "logout"}
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,29}")


class ContentError(ValueError):
    pass


# ------------------------------------------------------------------ validation
def _s(obj, key, maxlen, required=False):
    v = obj.get(key, "")
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise ContentError(f"'{key}' must be text.")
    v = v.replace("\r\n", "\n").replace("\r", "\n")
    v = "".join(ch for ch in v if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    if len(v) > maxlen:
        raise ContentError(f"'{key}' is too long (max {maxlen} characters).")
    if required and not v.strip():
        raise ContentError(f"'{key}' can't be empty.")
    return v


def _url(v):
    """Allowed link targets: https links, site paths, mailto, or @config keys like @email."""
    v = (v or "").strip()
    if not v:
        return ""
    if v.startswith("@") and v[1:] in LINK_KEYS:
        return v
    if re.fullmatch(r"https://[^\s\"'<>]{1,500}", v):
        return v
    if re.fullmatch(r"/[A-Za-z0-9/_.#%()~-]{0,300}", v):
        return v
    if re.fullmatch(r"mailto:[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", v):
        return v
    raise ContentError(f"Link '{v[:60]}' isn't allowed. Use https://..., /page, or @email / @discord / @youtube etc.")


def _section(sec):
    if not isinstance(sec, dict):
        raise ContentError("Bad section.")
    t = sec.get("type")
    if t not in SECTION_TYPES:
        raise ContentError(f"Unknown section type '{t}'.")
    out = {"type": t, "title": _s(sec, "title", 60), "color": sec.get("color") if sec.get("color") in COLORS else "green",
           "link_label": _s(sec, "link_label", 30), "link_url": _url(sec.get("link_url"))}
    if t == "text":
        out["text"] = _s(sec, "text", 6000)
        out["badge"] = _s(sec, "badge", 3)
        out["buttons"] = _links(sec.get("buttons", []), 4)
    elif t == "items":
        items = sec.get("items", [])
        if not isinstance(items, list) or len(items) > 30:
            raise ContentError("A list section can have up to 30 entries.")
        out["items"] = []
        for it in items:
            if not isinstance(it, dict):
                raise ContentError("Bad entry.")
            tags = it.get("tags", [])
            if not isinstance(tags, list) or len(tags) > 12:
                raise ContentError("Up to 12 tags per entry.")
            out["items"].append({
                "icon": _s(it, "icon", 3), "icon_color": it.get("icon_color") if it.get("icon_color") in ICON_COLORS else "green",
                "title": _s(it, "title", 100), "subtitle": _s(it, "subtitle", 100),
                "tags": [_s({"t": x}, "t", 30) for x in tags if isinstance(x, str) and x.strip()],
                "text": _s(it, "text", 4000), "url": _url(it.get("url")),
            })
    elif t == "links":
        out["style"] = sec.get("style") if sec.get("style") in LINK_STYLES else "list"
        out["items"] = _links(sec.get("items", []), 20)
    elif t == "videos":
        try:
            out["count"] = max(1, min(15, int(sec.get("count", 8))))
        except (TypeError, ValueError):
            out["count"] = 8
    elif t in ("marquee", "discord"):
        out["text"] = _s(sec, "text", 400)
    elif t == "blog":
        try:
            out["count"] = max(1, min(50, int(sec.get("count", 20))))
        except (TypeError, ValueError):
            out["count"] = 20
    return out


def _links(items, maxn):
    if not isinstance(items, list) or len(items) > maxn:
        raise ContentError(f"Up to {maxn} links.")
    out = []
    for it in items:
        if not isinstance(it, dict):
            raise ContentError("Bad link.")
        out.append({"label": _s(it, "label", 40, required=True), "sub": _s(it, "sub", 80),
                    "url": _url(it.get("url")), "color": it.get("color") if it.get("color") in BADGE_COLORS else "gray"})
    return out


def validate(content):
    if not isinstance(content, dict):
        raise ContentError("Bad content.")
    if len(json.dumps(content)) > 400_000:
        raise ContentError("Content is too big.")
    site = content.get("site") or {}
    if not isinstance(site, dict):
        raise ContentError("Bad site settings.")
    out = {"site": {
        "logo": _s(site, "logo", 30, required=True), "tagline": _s(site, "tagline", 120),
        "banner_label": _s(site, "banner_label", 30), "banner_text": _s(site, "banner_text", 120),
        "banner_url": _url(site.get("banner_url")), "page_title": _s(site, "page_title", 80, required=True),
        "description": _s(site, "description", 200), "footer": _s(site, "footer", 300),
    }, "tabs": []}
    tabs = content.get("tabs")
    if not isinstance(tabs, list) or not 1 <= len(tabs) <= 12:
        raise ContentError("You need between 1 and 12 tabs.")
    seen = set()
    for i, tab in enumerate(tabs):
        if not isinstance(tab, dict):
            raise ContentError("Bad tab.")
        title = _s(tab, "title", 20, required=True)
        slug = (tab.get("slug") or "").strip().lower()
        if i == 0:
            slug = "home"
        elif not SLUG_RE.fullmatch(slug) or slug in RESERVED_SLUGS or slug == "home":
            raise ContentError(f"Tab '{title}' needs a web address made of lowercase letters, numbers and dashes (not a reserved word).")
        if slug in seen:
            raise ContentError(f"Two tabs use the address '{slug}'.")
        seen.add(slug)
        t = {"slug": slug, "title": title, "hidden": bool(tab.get("hidden")) and i != 0,
             "heading": _s(tab, "heading", 60), "subheading": _s(tab, "subheading", 300),
             "page_title": _s(tab, "page_title", 80), "main": [], "side": []}
        used = set()
        for col in ("main", "side"):
            secs = tab.get(col, [])
            if not isinstance(secs, list) or len(secs) > 25:
                raise ContentError("Up to 25 sections per column.")
            for s in secs:
                v = _section(s)
                if v["type"] in SINGLE_USE:
                    if v["type"] in used:
                        raise ContentError(f"Tab '{title}' can only have one '{v['type']}' section.")
                    used.add(v["type"])
                t[col].append(v)
        out["tabs"].append(t)
    return out


# ------------------------------------------------------------------ text formatting
def _href(url, cfg):
    """Turn a stored link into a real href, or '' if it points at an unset setting."""
    if url.startswith("@"):
        val = cfg.get(url[1:], "")
        if url == "@email":
            return "mailto:" + val if val else ""
        return val
    return url


def _a(url, cfg, label_html, cls=""):
    href = _href(url, cfg)
    if not href:
        return None
    ext = href.startswith("https://")
    return '<a%s href="%s"%s>%s</a>' % (' class="%s"' % cls if cls else "", esc(href, quote=True),
                                        ' target="_blank" rel="noopener"' if ext else "", label_html)


def inline(text, cfg):
    s = esc(text, quote=True)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)

    def link(m):
        label, raw = m.group(1), html.unescape(m.group(2))
        try:
            u = _url(raw)
        except ContentError:
            return label
        return _a(u, cfg, label) or label
    return re.sub(r"\[([^\]\n]{1,200})\]\(([^)\s]{1,500})\)", link, s)


def rich(text, cfg):
    """Blank line = new paragraph. Lines starting with '- ' = bullet list. **bold**, *italic*, [label](link)."""
    out = []
    for block in re.split(r"\n\s*\n", (text or "").strip()):
        lines = [l for l in block.split("\n") if l.strip()]
        if not lines:
            continue
        if all(l.lstrip().startswith("- ") for l in lines):
            out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % inline(l.lstrip()[2:], cfg) for l in lines))
        else:
            out.append("<p>%s</p>" % "<br>".join(inline(l, cfg) for l in lines))
    return "\n".join(out)


# ------------------------------------------------------------------ rendering
def _box(sec, inner, cls="in"):
    color = {"green": "", "orange": ' class="or"', "black": ' class="bk"'}[sec.get("color", "green")]
    link = ""
    if sec.get("link_label") and sec.get("link_url"):
        a = _a(sec["link_url"], {}, esc(sec["link_label"]) + " &raquo;") if not sec["link_url"].startswith("@") else None
        if a:
            link = " <small>%s</small>" % a
    head = '        <h2%s>%s%s</h2>\n' % (color, esc(sec.get("title", "")), link) if sec.get("title") else ""
    return '      <div class="box">\n%s        <div class="%s">\n%s\n        </div>\n      </div>\n' % (head, cls, inner)


PLAYER = ('<iframe id="ytplayer" referrerpolicy="strict-origin-when-cross-origin" width="100%" height="340" '
          'src="https://www.youtube-nocookie.com/embed/videoseries?list=UU{channel}" title="YouTube video player" frameborder="0" '
          'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen '
          'style="display:block;border:3px solid #222;background:#000"></iframe>')


def render_section(sec, cfg, ctx):
    t = sec["type"]
    if t == "text":
        body = rich(sec.get("text", ""), cfg)
        btns = " ".join(filter(None, (_a(b["url"], cfg, esc(b["label"]), "btn g" if i == 0 else "btn")
                                       for i, b in enumerate(sec.get("buttons", [])))))
        if btns:
            body += '\n<p class="btnrow">%s</p>' % btns
        if sec.get("badge"):
            return _box(sec, '<div class="me">%s</div><div>%s</div>' % (esc(sec["badge"]), body), "in intro")
        return _box(sec, body, "in prose")
    if t == "items":
        rows = []
        for it in sec.get("items", []):
            icon = ('<div class="icon" style="background:%s">%s</div>' % (ICON_COLORS[it["icon_color"]], esc(it["icon"]))
                    if it.get("icon") else "")
            title = esc(it["title"])
            if it.get("url"):
                title = _a(it["url"], cfg, title) or title
            sub = '<div class="sub">%s</div>' % esc(it["subtitle"]) if it.get("subtitle") else ""
            tags = '<div class="tags">%s</div>' % "".join("<span>%s</span>" % esc(x) for x in it["tags"]) if it.get("tags") else ""
            rows.append('<div class="proj">%s<div><h4>%s</h4>%s%s%s</div></div>' % (icon, title, sub, tags, rich(it.get("text", ""), cfg)))
        return _box(sec, "\n".join(rows) or '<p class="empty">Nothing here yet.</p>')
    if t == "links":
        style = sec.get("style", "list")
        parts = []
        for i, l in enumerate(sec.get("items", [])):
            if style == "badges":
                a = _a(l["url"], cfg, '<span class="badge88" style="background:%s%s">%s</span>' % (
                    BADGE_COLORS[l["color"]], ";color:#000" if l["color"] == "yellow" else "", esc(l["label"])))
            elif style == "boxes":
                a = _a(l["url"], cfg, '%s<small>%s</small>' % (esc(l["label"]), esc(l["sub"])), "funbox")
            elif style == "buttons":
                a = _a(l["url"], cfg, esc(l["label"]), "btn g" if i == 0 else "btn")
            else:
                a = _a(l["url"], cfg, esc(l["label"]))
            if a:
                parts.append(a)
        if not parts:
            return ""
        cls = {"list": "in links", "buttons": "in btnrow", "boxes": "in fun", "badges": "in buddies"}[style]
        return _box(sec, " ".join(parts), cls)
    if t == "player":
        yt = cfg.get("youtube", "")
        inner = PLAYER.format(channel=esc(ctx["channel"][2:])) + (
            '<div class="vidinfo"><div><h3>ItsRaiden</h3></div><div style="text-align:right;white-space:nowrap">'
            '%s %s</div></div>' % (_a("@coffee", cfg, "&#9749; Buy Me a Coffee", "btn") or "",
                                   ('<a class="btn g" href="%s?sub_confirmation=1" target="_blank" rel="noopener">+ Subscribe</a>' % esc(yt)) if yt else ""))
        return _box(sec, inner)
    if t == "videos":
        return _box(sec, '<p class="empty">Loading videos...</p>', 'in grid autogrid" data-count="%d' % sec.get("count", 8))
    if t == "pics":
        return _box(sec, '<p class="empty">Loading pics...</p>', 'in grid3" id="pics" style="padding:18px')
    if t == "marquee":
        return '      <marquee scrollamount="4">%s</marquee>\n' % esc(sec.get("text", ""))
    if t == "discord":
        a = _a("@discord", cfg, "JOIN NOW!", "btn g bigjoin")
        if not a:
            return ""
        return _box(sec, '<div style="text-align:center;padding:14px"><p style="font-size:13px;margin-top:0">%s</p>%s</div>' % (
            esc(sec.get("text", "")), a))
    if t == "blog":
        posts = ctx["posts"][: sec.get("count", 20)]
        if not posts:
            return _box(sec, '<p class="empty">No posts yet. Check back soon!</p>')
        rows = []
        for p in posts:
            text = p["body"]
            short = text if len(text) <= 600 else text[:600].rsplit(" ", 1)[0] + "..."
            rows.append('<div class="post"><h4><a href="/blog-post/%s">%s</a></h4><div class="meta">%s</div>%s%s</div>' % (
                esc(p["slug"]), esc(p["title"]), esc(p["date"]), rich(short, cfg),
                '<p><a href="/blog-post/%s">Read more &raquo;</a></p>' % esc(p["slug"]) if len(text) > 600 else ""))
        return _box(sec, "\n".join(rows))
    if t == "poll":
        return _box(sec, "Loading...", "in poll\" id=\"poll")
    if t == "shoutbox":
        return _box(sec, '<div class="shout" id="shout"></div><div id="shoutform"></div>')
    if t == "counter":
        return '      <div style="text-align:center;font-weight:bold">%s<div id="counter"></div></div>\n' % (
            esc(sec.get("title") or "You are visitor number:"))
    return ""


def render_page(content, cfg, ctx, active_slug, left_html=None, right_html=None, title=None, robots=False):
    site = content["site"]
    tabs = content["tabs"]
    nav = "\n".join('    <a href="%s"%s>%s</a>' % ("/" if i == 0 else "/" + t["slug"],
                                                    ' class="on"' if t["slug"] == active_slug else "", esc(t["title"]))
                    for i, t in enumerate(tabs) if not t["hidden"] or t["slug"] == active_slug)
    tab = next((t for t in tabs if t["slug"] == active_slug), None)
    if left_html is None:
        head = ""
        if tab.get("heading"):
            head += '      <h1 class="pagehead">%s</h1>\n' % esc(tab["heading"])
        if tab.get("subheading"):
            head += '      <p class="pagesub">%s</p>\n' % inline(tab["subheading"], cfg)
        left_html = head + "".join(render_section(s, cfg, ctx) for s in tab["main"])
    if right_html is None:
        right_html = "".join(render_section(s, cfg, ctx) for s in tab["side"]) if tab else ""
    if title is None:
        title = (tab.get("page_title") if tab else "") or ("%s :: %s" % (tab["title"], site["page_title"]) if tab and active_slug != "home" else site["page_title"])
    banner_href = _href(site.get("banner_url", ""), cfg) or "/"
    banner = ('<a id="headnew" href="%s"><b>&#9733; %s</b> <span>%s</span></a>' % (
        esc(banner_href, quote=True), esc(site["banner_label"]), esc(site["banner_text"]))) if site.get("banner_text") else ""
    footer_links = " | ".join('<a href="%s">%s</a>' % ("/" if i == 0 else "/" + t["slug"], esc(t["title"]))
                              for i, t in enumerate(tabs) if not t["hidden"])
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>%s</title>
<meta name="description" content="%s">
%s<link rel="stylesheet" href="/style.css">
</head>
<body>
<div id="wrap">

  <div id="header">
    <a id="logo" href="/">%s</a>
    <div id="tagline">%s</div>
    <div id="login"></div>
    %s
  </div>
  <div id="nav">
%s
  </div>

  <div id="main">
    <div id="left">
%s
    </div>

    <div id="right">
%s
    </div>
  </div>

  <div id="footer">
    %s | <a href="/signup">Sign Up</a><br>
    %s
  </div>
</div>
<div id="lightbox"><img alt=""><span></span><small>(click anywhere to close)</small></div>
<script src="/site.js"></script>
</body>
</html>
""" % (esc(title), esc(site.get("description", ""), quote=True), '<meta name="robots" content="noindex">\n' if robots else "",
       esc(site["logo"]), esc(site.get("tagline", "")), banner, nav, left_html, right_html,
       footer_links, "<br>".join(inline(l, cfg) for l in site.get("footer", "").split("\n") if l.strip()))


def render_post(content, cfg, ctx, post):
    blog_tab = next((t for t in content["tabs"] if any(s["type"] == "blog" for s in t["main"])), None)
    back = ('<p><a href="/%s">&laquo; Back to %s</a></p>' % (esc(blog_tab["slug"]), esc(blog_tab["title"]))) if blog_tab else ""
    left = ('      <h1 class="pagehead">%s</h1>\n      <p class="pagesub">%s</p>\n'
            '      <div class="box"><div class="in prose">%s</div></div>\n      %s\n') % (
        esc(post["title"]), esc(post["date"]), rich(post["body"], cfg), back)
    side = "".join(render_section(s, cfg, ctx) for s in blog_tab["side"]) if blog_tab else ""
    return render_page(content, cfg, ctx, blog_tab["slug"] if blog_tab else "", left, side,
                       "%s :: %s" % (post["title"], content["site"]["page_title"]))


# ------------------------------------------------------------------ default content (first start)
DEFAULT = {
    "site": {
        "logo": "RAIDEN BRUNDIN",
        "tagline": "IT & systems administration • Linux • homelab • networking",
        "banner_label": "CURRENTLY:",
        "banner_text": "Systems Administration (IT) student • Nova Scotia, Canada",
        "banner_url": "",
        "page_title": "Raiden Brundin :: IT & Systems Administration",
        "description": "Raiden Brundin - IT and systems administration student in Nova Scotia, Canada. Linux, homelab and networking.",
        "footer": "© 2026 Raiden Brundin. Hosted on my own homelab server.\nBest viewed in Internet Explorer 7 or Firefox 3 at 1024x768",
    },
    "tabs": [
        {"slug": "home", "title": "Home", "hidden": False, "heading": "", "subheading": "", "page_title": "",
         "main": [
             {"type": "text", "title": "★ HI, I'M RAIDEN BRUNDIN", "color": "green", "badge": "RB",
              "text": "I'm a **Systems Administration (IT) student** in Nova Scotia, Canada. I like figuring out how systems fit together, then running them myself.\n\n"
                      "Outside of class I run my own **Linux homelab**, and this website is hosted on it. I've built and troubleshot my own PCs and used a lot of different Linux distros along the way.\n\n"
                      "I also make Minecraft videos on YouTube, which is what the [Videos](/videos) tab is for.",
              "buttons": [{"label": "✉ Get in touch", "url": "@email"}, {"label": "LinkedIn", "url": "@linkedin"}]},
             {"type": "items", "title": "EDUCATION", "color": "orange", "items": [
                 {"icon": "IT", "icon_color": "blue", "title": "Systems Administration (IT) Program", "subtitle": "",
                  "tags": ["2-year program", "In progress"],
                  "text": "Current coursework:\n\n- Cisco Networking Essentials (ITN)\n- Python programming\n- HTML / web fundamentals"}]},
             {"type": "items", "title": "PROJECTS", "color": "green", "items": [
                 {"icon": "⚙", "icon_color": "green", "title": "Home Server (Homelab)", "subtitle": "",
                  "tags": ["Debian", "Docker", "Runtipi", "Cloudflare Tunnel", "Tailscale"],
                  "text": "A Lenovo ThinkCentre M720q I set up as an always-on Linux server.\n\n"
                          "- Debian with Runtipi to deploy self-hosted apps in Docker\n- Hosts this website through a Cloudflare Tunnel\n"
                          "- Runs a Navidrome music server at music.raidenbrundin.com\n- Runs a public Minecraft server with Crafty Controller\n"
                          "- Remote admin access over Tailscale"},
                 {"icon": "m", "icon_color": "lime", "title": "Matcha Music", "subtitle": "",
                  "tags": ["Android", "Kotlin", "Jetpack Compose", "Subsonic API"],
                  "text": "An Android music player for self-hosted music libraries. It streams from Navidrome and other Subsonic-compatible servers, supports offline downloads, and is being prepared for release on Google Play."},
                 {"icon": "PC", "icon_color": "gray", "title": "PC Building & Linux", "subtitle": "",
                  "tags": ["Hardware", "Linux", "Troubleshooting"],
                  "text": "Built my own desktop (Intel i9-10900K, RTX 3080) and have run Arch-based distros, elementary OS and now Kubuntu on it.\n\n"
                          "- Resolved Intel RAID/VMD vs AHCI storage conflicts and GRUB boot problems\n"
                          "- Set up dual-booting Linux and Windows on separate NVMe drives\n- Configured NVIDIA drivers and a video editing setup on Linux"}]},
             {"type": "links", "title": "THE FUN STUFF", "color": "black", "style": "boxes", "items": [
                 {"label": "▶ Videos", "sub": "creepy Minecraft on YouTube", "url": "/videos"},
                 {"label": "\U0001F4F7 Pics", "sub": "screenshots & stuff", "url": "/pics"},
                 {"label": "\U0001F4AC Community", "sub": "shoutbox, polls, Discord", "url": "/community"}]},
         ],
         "side": [
             {"type": "items", "title": "SKILLS", "color": "green", "items": [
                 {"icon": "", "icon_color": "green", "title": "Linux", "subtitle": "", "tags": [],
                  "text": "Debian, Ubuntu / Kubuntu, Arch-based distros; installs, dual-booting, bootloader and driver troubleshooting"},
                 {"icon": "", "icon_color": "green", "title": "Self-hosting", "subtitle": "", "tags": [],
                  "text": "Docker, Runtipi, Cloudflare Tunnel, Tailscale, Navidrome"},
                 {"icon": "", "icon_color": "green", "title": "Networking", "subtitle": "", "tags": [],
                  "text": "Cisco Networking Essentials (ITN) coursework, Packet Tracer, router config & port forwarding, DNS / subdomains"},
                 {"icon": "", "icon_color": "green", "title": "Hardware", "subtitle": "", "tags": [],
                  "text": "PC building, BIOS/storage config (AHCI vs RAID), diagnosing failed parts"},
                 {"icon": "", "icon_color": "green", "title": "Coursework", "subtitle": "", "tags": [], "text": "Python, HTML"}]},
             {"type": "links", "title": "LINKS & CONTACT", "color": "orange", "style": "list", "items": [
                 {"label": "✉ Email me", "url": "@email"}, {"label": "LinkedIn", "url": "@linkedin"},
                 {"label": "GitHub", "url": "@github"}, {"label": "YouTube", "url": "@youtube"}]},
             {"type": "counter", "title": "You are visitor number:"},
         ]},
        {"slug": "blog", "title": "Blog", "hidden": False, "heading": "BLOG", "page_title": "",
         "subheading": "Notes on my homelab, Linux, school and whatever else I'm working on.",
         "main": [{"type": "blog", "title": "LATEST POSTS", "color": "green", "count": 20}],
         "side": [
             {"type": "links", "title": "LINKS & CONTACT", "color": "orange", "style": "list", "items": [
                 {"label": "✉ Email me", "url": "@email"}, {"label": "LinkedIn", "url": "@linkedin"},
                 {"label": "YouTube", "url": "@youtube"}]},
             {"type": "counter", "title": "You are visitor number:"}]},
        {"slug": "videos", "title": "Videos", "hidden": False, "heading": "VIDEOS!!!", "page_title": "Videos :: ItsRaiden",
         "subheading": "I make creepy Minecraft videos as **ItsRaiden**. Every upload shows up here automatically. Turn the lights off. Seriously.",
         "main": [
             {"type": "marquee", "text": "*** WELCOME TO ITSRAIDEN ON YOUTUBE!!! *** I'M BACK!!! *** Watch MISPLACED with SlinkGrenade *** Sign up and leave a shout!!! ***"},
             {"type": "player", "title": "★ LATEST UPLOAD", "color": "green", "link_label": "subscribe", "link_url": "https://www.youtube.com/@itsraidenfr?sub_confirmation=1"},
             {"type": "videos", "title": "ALL MY UPLOADS", "color": "orange", "count": 15, "link_label": "see them on YouTube", "link_url": "https://www.youtube.com/@itsraidenfr/videos"},
             {"type": "items", "title": "CHANNEL NEWS", "color": "black", "items": [
                 {"icon": "", "icon_color": "green", "title": "I'M BACK!!!", "subtitle": "Posted by Raiden", "tags": [],
                  "text": "After like 2 years away I'm finally making videos again. More creepy Minecraft, more horror maps, more SlinkGrenade screaming. Go subscribe!!"},
                 {"icon": "", "icon_color": "green", "title": "Misplaced is up!!", "subtitle": "Posted by Raiden", "tags": [],
                  "text": "Me and SlinkGrenade played a backrooms horror map and it was pure panic. Go watch it with the lights off."}]}],
         "side": [
             {"type": "poll", "title": "POLL!!!", "color": "orange"},
             {"type": "shoutbox", "title": "SHOUTBOX", "color": "green"},
             {"type": "links", "title": "BUDDIES", "color": "black", "style": "badges", "items": [
                 {"label": "YouTube", "url": "@youtube", "color": "red"}, {"label": "SlinkGrenade", "url": "@slinkgrenade", "color": "orange"},
                 {"label": "Discord", "url": "@discord", "color": "blue"}, {"label": "Buy Me a Coffee", "url": "@coffee", "color": "yellow"}]},
             {"type": "counter", "title": "You are visitor number:"}]},
        {"slug": "pics", "title": "Pics", "hidden": False, "heading": "PICS!!!", "page_title": "",
         "subheading": "Screenshots, setups and behind the scenes. Click a pic to make it big!",
         "main": [{"type": "pics", "title": "PHOTO ALBUM", "color": "green"}],
         "side": [{"type": "poll", "title": "POLL!!!", "color": "orange"}, {"type": "shoutbox", "title": "SHOUTBOX", "color": "green"},
                  {"type": "counter", "title": "You are visitor number:"}]},
        {"slug": "community", "title": "Community", "hidden": False, "heading": "COMMUNITY!!!", "page_title": "",
         "subheading": "Sign up to post in the shoutbox and vote in polls. Come say hi!!",
         "main": [
             {"type": "discord", "title": "★ JOIN THE DISCORD", "color": "green",
              "text": "Get pinged when new videos drop, hang out with other viewers, and send me creepy seeds and maps to play."},
             {"type": "text", "title": "WHO'S SLINKGRENADE?", "color": "orange",
              "text": "My partner in crime for the horror map videos.", "badge": "", "buttons": [{"label": "His channel", "url": "@slinkgrenade"}]},
             {"type": "text", "title": "THE RULES", "color": "black", "badge": "", "buttons": [],
              "text": "- Be nice. Seriously.\n- No spam or self-promo\n- No spoilers for videos that aren't out yet\n- Keep it PG-13\n- Herobrine is not allowed."}],
         "side": [{"type": "poll", "title": "POLL!!!", "color": "orange"}, {"type": "shoutbox", "title": "SHOUTBOX", "color": "green"},
                  {"type": "links", "title": "BUDDIES", "color": "black", "style": "badges", "items": [
                      {"label": "YouTube", "url": "@youtube", "color": "red"}, {"label": "SlinkGrenade", "url": "@slinkgrenade", "color": "orange"},
                      {"label": "Discord", "url": "@discord", "color": "blue"}, {"label": "Buy Me a Coffee", "url": "@coffee", "color": "yellow"}]},
                  {"type": "counter", "title": "You are visitor number:"}]},
    ],
}
DEFAULT = validate(copy.deepcopy(DEFAULT))

SYSTEM_BODIES = json.loads((Path(__file__).parent / "system_pages.json").read_text())
