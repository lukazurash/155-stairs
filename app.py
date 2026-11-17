import math
import os
import re
import secrets
import sqlite3
import smtplib
import threading
import time
import urllib.parse
import urllib.request
from email.message import EmailMessage
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, send_from_directory, session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from i18n import KA
from seed_text import SEED_INGREDIENTS

BASE = Path(__file__).parent
DB_PATH = Path(os.environ.get("DB_PATH", BASE / "data" / "cafe.db"))
UPLOADS = Path(os.environ.get("UPLOAD_DIR", BASE / "static" / "uploads"))
UPLOADS.mkdir(parents=True, exist_ok=True)
PRODUCTION = bool(os.environ.get("PRODUCTION"))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
DEMO_ADMIN = os.environ.get("DEMO_ADMIN") == "1"  # a read-only "look around" login for portfolio visitors

app = Flask(__name__)
app.config.update(SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
                  MAX_CONTENT_LENGTH=3 * 1024 * 1024, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=PRODUCTION)
if PRODUCTION:
    if app.config["SECRET_KEY"] == "dev-only-change-me" or ADMIN_PASSWORD == "admin123":
        raise RuntimeError("Set SECRET_KEY and ADMIN_PASSWORD before running in production.")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ICONS = ["cup", "plate", "cake", "glass", "wine"]
STATUSES = ["pending", "confirmed", "arrived", "no_show", "cancelled"]
ACTIVE = "('pending','confirmed','arrived')"  # statuses that hold a table
DIETS = ["vegetarian", "vegan", "gluten-free", "contains nuts"]
LOOKUPS = {}
DEFAULTS = {
    "name": "155 Stairs",
    "tagline": "A cozy cafe at the top of the stairs.",
    "about": "Climb the 155 steps and you will find a small, warm place with good coffee, homemade desserts and hearty dishes. Come for a quick espresso or stay for the evening.",
    "address": "Tbilisi, Georgia (demo address)",
    "phone": "+995 000 00 00 00",
    "email": "hello@155stairs.example",
    "currency": "₾",
    "table_count": "5",
    "seats_per_table": "4",
    "slot_minutes": "90",
    "max_days_ahead": "30",
    "auto_confirm": "0",
    "timezone": "Asia/Tbilisi",
    "logo": "",
    "cover": "",
    "chat_greeting": "Hi! Ask us anything, or tell us about a birthday or special occasion.",
    "max_group": "12",
    "special": "",
    "instagram": "",
    "whatsapp": "",
    "google_reviews": "",
    "color_dark": "#0f3a2c",
    "color_accent": "#1f6b4f",
    "color_gold": "#c9a24a",
    "font_style": "classic",
    "steps_count": "155",
    "steps_text": "steps up to a quiet corner with good coffee, warm light and homemade food.",
    "tagline_ka": "",
    "about_ka": "",
    "special_ka": "",
    "steps_text_ka": "",
    "chat_greeting_ka": "",
}
SEED_CATEGORIES = [("Starters", "plate"), ("Main dishes", "plate"), ("Desserts", "cake"),
                   ("Hot drinks", "cup"), ("Cold drinks", "glass"), ("Alcoholic drinks", "wine")]
SEED_DISHES = [  # category, name, description, price in tetri, tag, featured
    (1, "Pkhali trio", "Spinach, beetroot and green bean pâtés with walnuts and pomegranate.", 1400, "Vegetarian", 0),
    (1, "Tomato bruschetta", "Toasted bread, ripe tomatoes, basil and olive oil.", 1200, "Vegetarian", 0),
    (2, "Adjarian khachapuri", "Warm cheese bread with a runny egg and butter.", 1800, "House favourite", 1),
    (2, "Chicken in walnut sauce", "Tender chicken in a creamy walnut and herb sauce.", 2600, "", 0),
    (2, "Mushroom pasta", "Fresh pasta with forest mushrooms and cream.", 2200, "Vegetarian", 0),
    (3, "Honey cake", "Layers of honey sponge and soft cream.", 1100, "Homemade", 1),
    (3, "Baked cheesecake", "Creamy cheesecake with berry sauce.", 1200, "", 0),
    (4, "Espresso", "Rich and short.", 500, "", 0),
    (4, "Cappuccino", "Espresso with silky milk foam.", 700, "", 1),
    (4, "Hot chocolate", "Thick, dark and warming.", 800, "", 0),
    (5, "Homemade lemonade", "Fresh lemon, mint and a little honey.", 700, "", 0),
    (5, "Iced coffee", "Cold espresso over ice with milk.", 800, "", 0),
    (6, "House red wine (glass)", "Georgian red, smooth and dry.", 900, "", 0),
    (6, "House white wine (glass)", "Georgian white, crisp and fruity.", 900, "", 0),
    (6, "Craft beer", "Local craft beer, ask for today's choice.", 800, "", 0),
]


# ---------- language (English / Georgian) ----------
def lang():
    return "ka" if request.cookies.get("lang") == "ka" else "en"


def tr(text):
    return KA.get(text, text) if lang() == "ka" else text


def loc(obj, field):
    """Georgian text if the owner filled it in, otherwise the English text."""
    if lang() == "ka":
        try:
            value = obj[field + "_ka"]
        except (KeyError, IndexError):
            value = ""
        if value:
            return value
    return obj[field]


app.add_template_global(lang, "lang")
app.add_template_global(tr, "_")
app.add_template_global(loc, "loc")
ASSET_V = int(max(f.stat().st_mtime for f in (BASE / "static").rglob("*") if f.is_file() and "uploads" not in f.parts))


@app.get("/lang/<code>")
def set_lang(code):
    nxt = request.args.get("next", "/")
    if not nxt.startswith("/") or nxt.startswith("//") or "\\" in nxt:
        nxt = "/"
    resp = redirect(nxt)
    resp.set_cookie("lang", "ka" if code == "ka" else "en", max_age=31536000, samesite="Lax", secure=PRODUCTION)
    return resp


def hours_groups(rows):
    """Group days with the same hours: 'Every day 09:00 - 22:00' instead of seven lines."""
    groups = []
    for h in rows:
        key = (h["closed"], h["open"], h["close"])
        if groups and groups[-1]["key"] == key:
            groups[-1]["days"].append(h["day"])
        else:
            groups.append({"key": key, "days": [h["day"]]})
    out = []
    for g in groups:
        d = g["days"]
        label = tr("Every day") if len(d) == 7 else tr(DAYS[d[0]]) if len(d) == 1 else f"{tr(DAYS[d[0]])} - {tr(DAYS[d[-1]])}"
        out.append({"label": label, "text": tr("Closed") if g["key"][0] else f"{g['key'][1]} - {g['key'][2]}"})
    return out


@app.template_filter("tablenames")
def tablenames(csv):
    names = {str(t["id"]): t["name"] for t in db().execute("SELECT id, name FROM dining_tables")}
    return " + ".join(names.get(x, "#" + x) for x in (csv or "").split(",") if x)


# ---------- database ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, isolation_level=None)  # autocommit; transactions are explicit
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    con = g.pop("db", None)
    if con:
        con.close()


def add_column(con, table, name, ddl):
    if name not in [c[1] for c in con.execute(f"PRAGMA table_info({table})")]:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS hours(day INTEGER PRIMARY KEY, open TEXT NOT NULL, close TEXT NOT NULL, closed INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, icon TEXT NOT NULL DEFAULT 'plate', sort INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS dishes(id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER NOT NULL, name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '', price_cents INTEGER NOT NULL, tag TEXT NOT NULL DEFAULT '', image TEXT,
            featured INTEGER NOT NULL DEFAULT 0, visible INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS reservations(id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
            phone TEXT NOT NULL, email TEXT NOT NULL DEFAULT '', date TEXT NOT NULL, time TEXT NOT NULL, guests INTEGER NOT NULL,
            table_no INTEGER NOT NULL, notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
            created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    """)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS dining_tables(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, zone TEXT NOT NULL DEFAULT 'inside', seats INTEGER NOT NULL DEFAULT 4, image TEXT, description TEXT NOT NULL DEFAULT '', name_ka TEXT NOT NULL DEFAULT '', description_ka TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS enquiries(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL, email TEXT NOT NULL DEFAULT '', date TEXT NOT NULL DEFAULT '', guests TEXT NOT NULL DEFAULT '', message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS closures(id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, start TEXT NOT NULL DEFAULT '', end TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS gallery(id INTEGER PRIMARY KEY AUTOINCREMENT, image TEXT NOT NULL, caption TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, rating INTEGER NOT NULL, text TEXT NOT NULL,
            visible INTEGER NOT NULL DEFAULT 1, sample INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS chats(id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
            created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, last_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS chat_messages(id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, sender TEXT NOT NULL,
            body TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, seen INTEGER NOT NULL DEFAULT 0);
    """)
    had_section = "section" in [c[1] for c in con.execute("PRAGMA table_info(categories)")]
    had_ing = "ingredients" in [c[1] for c in con.execute("PRAGMA table_info(dishes)")]
    add_column(con, "categories", "section", "TEXT NOT NULL DEFAULT 'food'")
    add_column(con, "dishes", "ingredients", "TEXT NOT NULL DEFAULT ''")
    add_column(con, "dishes", "sold_out", "INTEGER NOT NULL DEFAULT 0")
    add_column(con, "dishes", "diet", "TEXT NOT NULL DEFAULT ''")
    for col in ("name_ka", "description_ka", "ingredients_ka"):
        add_column(con, "dishes", col, "TEXT NOT NULL DEFAULT ''")
    add_column(con, "categories", "name_ka", "TEXT NOT NULL DEFAULT ''")
    add_column(con, "reservations", "tables", "TEXT NOT NULL DEFAULT ''")
    add_column(con, "reservations", "source", "TEXT NOT NULL DEFAULT 'web'")
    add_column(con, "gallery", "caption_ka", "TEXT NOT NULL DEFAULT ''")
    con.execute("UPDATE reservations SET tables=CAST(table_no AS TEXT) WHERE tables=''")
    for k, v in DEFAULTS.items():
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    if con.execute("SELECT COUNT(*) FROM dining_tables").fetchone()[0] == 0:  # first run: start from the old table settings
        vals = dict(con.execute("SELECT key, value FROM settings"))
        n, per = int(vals.get("table_count", DEFAULTS["table_count"])), int(vals.get("seats_per_table", DEFAULTS["seats_per_table"]))
        inside = math.ceil(n * 0.6)
        for i in range(1, n + 1):
            con.execute("INSERT INTO dining_tables(id,name,zone,seats) VALUES(?,?,?,?)", (i, f"Table {i}", "inside" if i <= inside else "outside", per))
    if con.execute("SELECT COUNT(*) FROM hours").fetchone()[0] == 0:
        for d in range(7):
            con.execute("INSERT INTO hours(day,open,close,closed) VALUES(?,?,?,0)", (d, "09:00", "22:00"))
    if con.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
        for i, (n, ic) in enumerate(SEED_CATEGORIES, 1):
            con.execute("INSERT INTO categories(name,icon,sort) VALUES(?,?,?)", (n, ic, i))
        for c, n, d, p, t, f in SEED_DISHES:
            con.execute("INSERT INTO dishes(category_id,name,description,price_cents,tag,featured) VALUES(?,?,?,?,?,?)", (c, n, d, p, t, f))
    if not had_ing:
        for name, ing in SEED_INGREDIENTS.items():
            con.execute("UPDATE dishes SET ingredients=? WHERE name=? AND ingredients=''", (ing, name))
    if not had_section:
        con.execute("UPDATE categories SET section='drinks' WHERE name IN ('Hot drinks','Cold drinks','Alcoholic drinks')")
    if not con.execute("SELECT 1 FROM settings WHERE key='reviews_seeded'").fetchone():
        con.execute("INSERT INTO settings(key,value) VALUES('reviews_seeded','1')")
    con.commit()
    con.close()


def S():
    if "S" not in g:
        d = dict(DEFAULTS)
        for r in db().execute("SELECT key, value FROM settings"):
            if r["key"] != "admin_hash":
                d[r["key"]] = r["value"]
        row = db().execute("SELECT COUNT(*) AS n, COALESCE(SUM(seats),0) AS total, COALESCE(MAX(seats),1) AS biggest FROM dining_tables WHERE active=1").fetchone()
        d["table_count"], d["total_seats"], d["seats_per_table"] = str(row["n"]), str(row["total"]), str(row["biggest"])
        g.S = d
    return g.S


def tz():
    try:
        return ZoneInfo(S()["timezone"])
    except (ZoneInfoNotFoundError, KeyError):
        return timezone(timedelta(hours=4))


def mins(hhmm):
    if not re.fullmatch(r"\d{2}:\d{2}", hhmm or ""):
        raise ValueError("bad time")
    h, m = int(hhmm[:2]), int(hhmm[3:])
    if h > 24 or m > 59:
        raise ValueError("bad time")
    return h * 60 + m


def fmt(t):
    return f"{t // 60:02d}:{t % 60:02d}"


@app.template_filter("money")
def money(cents):
    return f"{cents / 100:.2f}"


@app.context_processor
def inject():
    ctx = {"s": S(), "hours": db().execute("SELECT * FROM hours ORDER BY day").fetchall(), "day_names": DAYS, "v": ASSET_V}
    ctx["hours_groups"] = hours_groups(ctx["hours"])
    cover = db().execute("SELECT image FROM gallery ORDER BY CAST(id AS TEXT)=? DESC, id LIMIT 1", (S()["cover"],)).fetchone()
    ctx["og_image"] = request.url_root.rstrip("/") + cover["image"] if cover else None  # the picture link previews show
    session.setdefault("csrf", secrets.token_hex(16))
    ctx["csrf"] = session["csrf"]
    if session.get("admin"):
        today = datetime.now(tz()).date().isoformat()
        ctx["new_requests"] = db().execute("SELECT COUNT(*) FROM enquiries WHERE status='new'").fetchone()[0]
        ctx["unread"] = db().execute("SELECT COUNT(*) FROM chat_messages WHERE sender='visitor' AND seen=0").fetchone()[0]
        ctx["pending_count"] = db().execute("SELECT COUNT(*) FROM reservations WHERE status='pending' AND date>=?", (today,)).fetchone()[0]
    return ctx


@app.after_request
def headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    if PRODUCTION:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000"  # browsers go straight to https next time
    return resp


# ---------- alerts to the owner (Telegram and/or email) ----------
def notify(text):
    """Send an alert in the background. Configure with environment variables (see README); does nothing if unset."""
    def work():
        token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
        if token and chat:
            try:
                data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
                urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data), timeout=8)
            except Exception:
                pass
        host, to = os.environ.get("SMTP_HOST"), os.environ.get("NOTIFY_EMAIL")
        if host and to:
            try:
                msg = EmailMessage()
                msg["Subject"], msg["From"], msg["To"] = text.splitlines()[0][:100], os.environ.get("SMTP_USER") or to, to
                msg.set_content(text)
                with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=10) as smtp:
                    smtp.starttls()
                    if os.environ.get("SMTP_USER"):
                        smtp.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
                    smtp.send_message(msg)
            except Exception:
                pass
    threading.Thread(target=work, daemon=True).start()


# ---------- booking logic ----------
def blocked(day_str, start, length):
    for c in db().execute("SELECT start, end FROM closures WHERE date=?", (day_str,)):
        if not c["start"] or (mins(c["start"]) < start + length and start < mins(c["end"])):
            return True
    return False


def free_tables(day_str, start, length):
    taken = taken_tables(day_str, start, length)
    return [t for t in db().execute("SELECT * FROM dining_tables WHERE active=1 ORDER BY seats, id") if t["id"] not in taken]


def allocate(day_str, start, length, guests):
    """Best-fit tables for staff bookings: the smallest single table that fits, else the biggest tables combined."""
    free = free_tables(day_str, start, length)
    fits = [t for t in free if t["seats"] >= guests]
    if fits:
        return [fits[0]["id"]]
    chosen, total = [], 0
    for t in sorted(free, key=lambda t: -t["seats"]):
        chosen.append(t["id"])
        total += t["seats"]
        if total >= guests:
            return chosen
    return None

def slots_for(day):
    row = db().execute("SELECT * FROM hours WHERE day=?", (day.weekday(),)).fetchone()
    if not row or row["closed"]:
        return []
    o, c, length = mins(row["open"]), mins(row["close"]), int(S()["slot_minutes"])
    out, t = [], o
    while t + length <= c:
        out.append(t)
        t += 30
    return out


def taken_tables(day_str, start, length):
    taken = set()
    for r in db().execute(f"SELECT table_no, tables, time FROM reservations WHERE date=? AND status IN {ACTIVE}", (day_str,)):
        rs = mins(r["time"])
        if rs < start + length and start < rs + length:
            taken.update(int(x) for x in (r["tables"] or str(r["table_no"])).split(","))
    return taken


def booking_window():
    now = datetime.now(tz())
    return now, now.date(), now.date() + timedelta(days=int(S()["max_days_ahead"]))


@app.get("/api/availability")
def availability():
    try:
        day = date.fromisoformat(request.args.get("date", ""))
    except ValueError:
        return jsonify(error="Pick a date."), 400
    now, today, last = booking_window()
    if not today <= day <= last:
        return jsonify(error="That date is not open for booking."), 400
    length, guests = int(S()["slot_minutes"]), max(1, request.args.get("guests", 2, type=int))
    out = []
    for st in slots_for(day):
        if day == today and st < now.hour * 60 + now.minute + 30:
            continue
        if blocked(day.isoformat(), st, length):
            continue
        free = free_tables(day.isoformat(), st, length)
        seats = sum(t["seats"] for t in free)
        out.append({"time": fmt(st), "tables": len(free) if seats >= guests else 0, "seats": seats})
    return jsonify(slots=out, total_seats=int(S()["total_seats"]))


@app.get("/api/tables")
def api_tables():
    """Only the tables that are free at the chosen time: booked ones are not shown at all."""
    try:
        day, start = date.fromisoformat(request.args.get("date", "")), mins(request.args.get("time", ""))
    except ValueError:
        return jsonify([])
    now, today, last = booking_window()
    length = int(S()["slot_minutes"])
    if not today <= day <= last or start not in slots_for(day) or blocked(day.isoformat(), start, length):
        return jsonify([])
    return jsonify([{"id": t["id"], "name": loc(t, "name"), "zone": t["zone"], "seats": t["seats"], "image": t["image"],
                     "description": loc(t, "description")} for t in free_tables(day.isoformat(), start, length)])


# ---------- public pages ----------
def menu_data(section=None):
    cats = db().execute("SELECT * FROM categories" + (" WHERE section=?" if section else "") + " ORDER BY sort, id",
                        (section,) if section else ()).fetchall()
    ids = {c["id"] for c in cats}
    dishes = [d for d in db().execute("SELECT d.*, c.icon FROM dishes d JOIN categories c ON c.id=d.category_id WHERE d.visible=1 ORDER BY d.id")
              if d["category_id"] in ids]
    return cats, dishes


def social():
    photos = db().execute("SELECT * FROM gallery ORDER BY id").fetchall()
    cover = next((x for x in photos if str(x["id"]) == S()["cover"]), photos[0] if photos else None)
    reviews = db().execute("SELECT * FROM reviews WHERE visible=1 ORDER BY id DESC").fetchall()
    avg = round(sum(r["rating"] for r in reviews) / len(reviews), 1) if reviews else None
    slides = ([cover] + [x for x in photos if x["id"] != cover["id"]])[:5] if cover else []
    return dict(photos=photos, cover=cover, slides=slides, reviews=reviews, avg=avg)


@app.get("/")
def home():
    _, dishes = menu_data()
    fav = [d for d in dishes if d["featured"]][:3] or dishes[:3]
    _, today, last = booking_window()
    return render_template("home.html", favourites=fav, today=today.isoformat(), last=last.isoformat(), **social())


@app.get("/menu")
def menu():
    cats, dishes = menu_data("food")
    return render_template("menu.html", heading="Menu", intro="Fresh, homemade and made to share.", cats=cats, dishes=dishes)


@app.get("/drinks")
def drinks():
    cats, dishes = menu_data("drinks")
    return render_template("menu.html", heading="Drinks", intro="Coffee, fresh drinks, wine and beer.", cats=cats, dishes=dishes)


@app.get("/about")
def about():
    return redirect("/#about")


@app.get("/contact")
def contact():
    return render_template("contact.html")


@app.get("/favicon.ico")
def favicon():
    return redirect("/static/favicon.svg", 301)  # for browsers and crawlers that ask for the old file name


PUBLIC_PAGES = ["/", "/menu", "/drinks", "/events", "/contact", "/reserve"]


@app.get("/robots.txt")
def robots():
    return f"User-agent: *\nDisallow: /admin\nSitemap: {request.url_root}sitemap.xml\n", 200, {"Content-Type": "text/plain"}


@app.get("/sitemap.xml")
def sitemap():
    urls = "".join(f"<url><loc>{request.url_root.rstrip('/')}{p}</loc></url>" for p in PUBLIC_PAGES)
    return (f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
            200, {"Content-Type": "application/xml"})


@app.errorhandler(404)
def not_found(_):
    if request.path.startswith("/api/"):
        return jsonify(error="Not found."), 404
    return render_template("404.html"), 404


@app.get("/media/<path:name>")
def media(name):
    return send_from_directory(UPLOADS, name, max_age=2592000)  # file names are random, so long caching is safe


def reserve_page(error=None, form=None, status=200):
    _, today, last = booking_window()
    return render_template("reserve.html", error=error, form=form if form is not None else request.args,
                           today=today.isoformat(), tomorrow=(today + timedelta(days=1)).isoformat(), last=last.isoformat()), status


@app.get("/reserve")
def reserve():
    return reserve_page()


@app.post("/reserve")
def reserve_post():
    f, s = request.form, S()
    if f.get("website"):  # hidden field that only bots fill in
        return redirect(url_for("home"))
    if not csrf_ok():
        return reserve_page(EXPIRED, f, 400)
    name = f.get("name", "").strip()[:80]
    phone = re.sub(r"[^\d+]", "", f.get("phone", ""))
    email = f.get("email", "").strip()[:120]
    notes = f.get("notes", "").strip()[:500]
    length, most = int(s["slot_minutes"]), min(int(s["max_group"]), int(s["total_seats"]))
    try:
        day = date.fromisoformat(f.get("date", ""))
        start = mins(f.get("time", ""))
        guests = int(f.get("guests", "0"))
    except ValueError:
        return reserve_page("Please choose a date, a time and the number of guests.", f, 400)
    now, today, last = booking_window()
    if len(name) < 2:
        return reserve_page("Please enter your name.", f, 400)
    if not 7 <= len(phone.replace("+", "")) <= 15:
        return reserve_page("Please enter a phone number we can reach you on.", f, 400)
    if email and not re.fullmatch(r"\S+@\S+\.\S+", email):
        return reserve_page("That email address does not look right.", f, 400)
    if not 1 <= guests <= most:
        return reserve_page(f"We can seat up to {most} guests in one booking. For a bigger group, please chat or call us.", f, 400)
    if (not today <= day <= last or start not in slots_for(day) or blocked(day.isoformat(), start, length)
            or (day == today and start < now.hour * 60 + now.minute + 30)):
        return reserve_page("That time is not available. Please pick another.", f, 400)
    wanted = sorted({int(x) for x in f.getlist("tables") if x.isdigit()})
    if not wanted:
        return reserve_page("Please choose a table.", f, 400)

    con, error, ref, ok, chosen = db(), None, "155-" + secrets.token_hex(3).upper(), False, []
    con.execute("BEGIN IMMEDIATE")  # lock so two people cannot take the same table
    try:
        d = day.isoformat()
        free = {t["id"]: t for t in free_tables(d, start, length)}
        chosen = [free[i] for i in wanted if i in free]
        seats = sum(t["seats"] for t in chosen)
        clash = [r for r in con.execute(f"SELECT time FROM reservations WHERE phone=? AND date=? AND status IN {ACTIVE}", (phone, d))
                 if mins(r["time"]) < start + length and start < mins(r["time"]) + length]
        upcoming = con.execute(f"SELECT COUNT(*) FROM reservations WHERE phone=? AND date>=? AND status IN {ACTIVE}", (phone, today.isoformat())).fetchone()[0]
        if len(chosen) != len(wanted):
            error = "Sorry, that table was just taken. Please choose another."
        elif seats < guests:
            error = "The tables you chose are too small for your group. Please choose more seats."
        elif seats - min(t["seats"] for t in chosen) >= guests:
            error = "You chose more tables than your group needs. Please remove one."
        elif clash:
            error = "You already have a table booked around that time. Please contact us to change it."
        elif upcoming >= 3:
            error = "You already have 3 upcoming reservations. Please contact us to change them."
        else:
            status = "confirmed" if s["auto_confirm"] == "1" else "pending"
            con.execute("INSERT INTO reservations(ref,name,phone,email,date,time,guests,table_no,tables,notes,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (ref, name, phone, email, d, fmt(start), guests, chosen[0]["id"], ",".join(str(t["id"]) for t in chosen), notes, status))
            ok = True
    finally:
        con.execute("COMMIT" if ok else "ROLLBACK")
    if error:
        return reserve_page(error, f, 409)
    session["my_refs"] = (session.get("my_refs", []) + [ref])[-10:]  # only this browser may open the confirmation page
    notify(f"New reservation ({'confirmed' if s['auto_confirm'] == '1' else 'needs confirmation'})\n{name}, {guests} guests\n{d} at {fmt(start)}, {' + '.join(t['name'] for t in chosen)}\nPhone: {phone}"
           + (f"\nNotes: {notes}" if notes else "") + f"\nRef {ref}\n{request.host_url}admin/reservations")
    return redirect(url_for("reserved", ref=ref))


def too_many_tries():
    """Allow 10 lookups or requests per visitor (IP address) every 10 minutes."""
    ip, now = request.remote_addr, time.time()
    LOOKUPS[ip] = [t for t in LOOKUPS.get(ip, []) if now - t < 600]
    if len(LOOKUPS[ip]) >= 10:
        return True
    LOOKUPS[ip].append(now)
    return False


@app.route("/manage", methods=["GET", "POST"])
def manage():
    r, error = None, None
    if request.method == "POST":
        if not csrf_ok():
            return render_template("manage.html", r=None, error=EXPIRED), 400
        if too_many_tries():
            return render_template("manage.html", r=None, error="Too many tries. Please wait 10 minutes."), 429
        r = db().execute("SELECT * FROM reservations WHERE ref=? AND phone=?", (request.form.get("ref", "").strip().upper(),
                         re.sub(r"[^\d+]", "", request.form.get("phone", "")))).fetchone()
        if not r:
            error = "We could not find a booking with that reference and phone number."
    return render_template("manage.html", r=r, error=error)


@app.post("/manage/cancel")
def manage_cancel():
    if not csrf_ok():
        return render_template("manage.html", r=None, error=EXPIRED), 400
    if too_many_tries():
        return render_template("manage.html", r=None, error="Too many tries. Please wait 10 minutes."), 429
    ref, phone =request.form.get("ref", "").strip().upper(), re.sub(r"[^\d+]", "", request.form.get("phone", ""))
    r = db().execute("SELECT * FROM reservations WHERE ref=? AND phone=?", (ref, phone)).fetchone()
    if r and r["status"] in ("pending", "confirmed"):
        db().execute("UPDATE reservations SET status='cancelled' WHERE id=?", (r["id"],))
        notify(f"Reservation cancelled by the guest\n{r['name']}, {r['guests']} guests\n{r['date']} at {r['time']}\nRef {ref}")
        return render_template("manage.html", r=None, error=None, done=True)
    return render_template("manage.html", r=None, error="That booking can no longer be cancelled online. Please call us.")


@app.get("/reserved/<ref>")
def reserved(ref):
    if ref not in session.get("my_refs", []) and not (session.get("admin") and not session.get("demo")):
        return redirect(url_for("manage"))  # strangers must give the phone number too
    r = db().execute("SELECT * FROM reservations WHERE ref=?", (ref,)).fetchone()
    if not r:
        abort(404)
    return render_template("reserved.html", r=r)


# ---------- admin ----------
FAILS = {}
EXPIRED = "This page was open for too long. Please try again."


def csrf_ok():
    """True when the form carries this visitor's secret token, so it came from our own page."""
    token = session.get("csrf", "")
    return bool(token) and secrets.compare_digest(request.form.get("csrf", ""), token)


def check_csrf():
    if not csrf_ok():
        abort(400)


def admin_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return view(*a, **kw)
    return wrapper


def password_ok(pw):
    row = db().execute("SELECT value FROM settings WHERE key='admin_hash'").fetchone()
    return check_password_hash(row["value"], pw) if row else secrets.compare_digest(pw, ADMIN_PASSWORD)


DEMO_NOTE = "This is a read-only demo: nothing was changed. Guests' personal details are hidden."


@app.before_request
def demo_is_read_only():
    if session.get("demo") and request.method == "POST" and request.path.startswith("/admin/")             and request.path not in ("/admin/logout", "/admin/login", "/admin/demo"):
        flash(DEMO_NOTE)
        back = urllib.parse.urlparse(request.referrer or "").path
        return redirect(back if back.startswith("/admin/") else url_for("admin_reservations"))


def private(rows, *fields):
    """Rows as the demo visitor may see them: guests' names, phones, emails and messages masked."""
    if not session.get("demo"):
        return rows
    def mask(field, v):
        if not v:
            return v
        if field == "phone":
            return "+995 ••• ••• " + v[-2:]
        if field == "name":
            return v[0] + "•••"
        return "(hidden in the demo)"
    return [{**dict(r), **{f: mask(f, r[f]) for f in fields}} for r in rows]


@app.post("/admin/demo")
def demo_login():
    check_csrf()
    if not DEMO_ADMIN:
        abort(404)
    session.clear()
    session["admin"] = session["demo"] = True
    flash(DEMO_NOTE)
    return redirect(url_for("admin_reservations"))


@app.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        check_csrf()
        ip, now = request.remote_addr, time.time()
        FAILS[ip] = [t for t in FAILS.get(ip, []) if now - t < 600]
        if len(FAILS[ip]) >= 5:
            flash("Too many attempts. Please wait 10 minutes.")
            return render_template("admin_login.html", demo_admin=DEMO_ADMIN), 429
        if password_ok(request.form.get("password", "")):
            session.clear()
            session["admin"] = True
            return redirect(url_for("admin_reservations"))
        FAILS[ip].append(now)
        flash("Wrong password.")
    return render_template("admin_login.html", demo_admin=DEMO_ADMIN)


@app.post("/admin/logout")
def logout():
    check_csrf()
    session.clear()
    return redirect(url_for("login"))


@app.get("/admin")
@admin_required
def admin():
    return redirect(url_for("admin_reservations"))


@app.get("/admin/reservations")
@admin_required
def admin_reservations():
    today = datetime.now(tz()).date()
    try:
        day = date.fromisoformat(request.args.get("date", "")).isoformat()
    except ValueError:
        day = today.isoformat()
    guest = ("name", "phone", "email", "notes")
    rows = private(db().execute("SELECT * FROM reservations WHERE date=? ORDER BY time, table_no", (day,)).fetchall(), *guest)
    pending = private(db().execute("SELECT * FROM reservations WHERE status='pending' AND date>=? ORDER BY date, time", (today.isoformat(),)).fetchall(), *guest)
    upcoming = db().execute("""SELECT date, COUNT(*) AS n, SUM(guests) AS guests FROM reservations
        WHERE status IN ('confirmed','arrived') AND date>? AND date<=? GROUP BY date ORDER BY date""",
                            (today.isoformat(), (today + timedelta(days=7)).isoformat())).fetchall()
    return render_template("admin_reservations.html", tab="reservations", day=day, rows=rows, pending=pending,
                           upcoming=upcoming, seats=int(S()["total_seats"]))


@app.post("/admin/reservations/new")
@admin_required
def admin_reservation_new():
    check_csrf()
    f = request.form
    name, notes = f.get("name", "").strip()[:80] or "Walk-in", f.get("notes", "").strip()[:500]
    phone = re.sub(r"[^\d+]", "", f.get("phone", ""))
    length = int(S()["slot_minutes"])
    try:
        day, start, guests = date.fromisoformat(f.get("date", "")), mins(f.get("time", "")), int(f.get("guests", "0"))
    except ValueError:
        flash("Enter a date, a time like 18:30 and the number of guests.")
        return redirect(url_for("admin_reservations"))
    if not 1 <= guests <= int(S()["total_seats"]):
        flash(f"The cafe seats {S()['total_seats']} guests in total.")
        return redirect(url_for("admin_reservations", date=day.isoformat()))
    con, chosen, ok = db(), None, False
    con.execute("BEGIN IMMEDIATE")
    try:
        chosen = allocate(day.isoformat(), start, length, guests)
        if chosen:
            con.execute("INSERT INTO reservations(ref,name,phone,date,time,guests,table_no,tables,notes,status,source) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        ("155-" + secrets.token_hex(3).upper(), name, phone, day.isoformat(), fmt(start), guests, chosen[0],
                         ",".join(map(str, chosen)), notes, "confirmed", "staff"))
            ok = True
    finally:
        con.execute("COMMIT" if ok else "ROLLBACK")
    flash(f"Booked {tablenames(','.join(map(str, chosen)))} for {name}." if ok else "Not enough free tables at that time.")
    return redirect(url_for("admin_reservations", date=day.isoformat()))


@app.route("/admin/closures", methods=["GET", "POST"])
@admin_required
def admin_closures():
    if request.method == "POST":
        check_csrf()
        f = request.form
        try:
            day = date.fromisoformat(f.get("date", "")).isoformat()
            a, b = ("", "") if f.get("whole") else (f.get("start", ""), f.get("end", ""))
            if a and not mins(a) < mins(b):
                raise ValueError
        except ValueError:
            flash("Choose a date, and either tick the whole day or give a start time before the end time.")
            return redirect(url_for("admin_closures"))
        db().execute("INSERT INTO closures(date,start,end,reason) VALUES(?,?,?,?)", (day, a, b, f.get("reason", "").strip()[:100]))
        hit = [r for r in db().execute(f"SELECT time FROM reservations WHERE date=? AND status IN {ACTIVE}", (day,))
               if not a or (mins(r["time"]) < mins(b) and mins(a) < mins(r["time"]) + int(S()["slot_minutes"]))]
        flash("Blocked." + (f" Careful: {len(hit)} existing booking(s) fall in this period. Please contact those guests." if hit else ""))
        return redirect(url_for("admin_closures"))
    rows = db().execute("SELECT * FROM closures WHERE date>=? ORDER BY date, start", (datetime.now(tz()).date().isoformat(),)).fetchall()
    return render_template("admin_closures.html", tab="closures", rows=rows)


@app.post("/admin/closures/<int:cid>/delete")
@admin_required
def admin_closure_delete(cid):
    check_csrf()
    db().execute("DELETE FROM closures WHERE id=?", (cid,))
    return redirect(url_for("admin_closures"))


@app.post("/admin/menu/<int:did>/soldout")
@admin_required
def admin_soldout(did):
    check_csrf()
    db().execute("UPDATE dishes SET sold_out=1-sold_out WHERE id=?", (did,))
    return redirect(url_for("admin_menu"))


@app.post("/admin/password")
@admin_required
def admin_password():
    check_csrf()
    f = request.form
    if not password_ok(f.get("current", "")):
        flash("The current password is wrong.")
    elif len(f.get("new", "")) < 10:
        flash("Use at least 10 characters for the new password.")
    elif f.get("new") != f.get("again"):
        flash("The two new passwords do not match.")
    else:
        db().execute("INSERT OR REPLACE INTO settings(key,value) VALUES('admin_hash',?)", (generate_password_hash(f["new"]),))
        flash("Password changed.")
    return redirect(url_for("admin_settings"))


@app.post("/admin/reservations/<int:rid>/status")
@admin_required
def admin_reservation_status(rid):
    check_csrf()
    r = db().execute("SELECT date, time, name FROM reservations WHERE id=?", (rid,)).fetchone()
    if r and request.form.get("status") in STATUSES:
        db().execute("UPDATE reservations SET status=? WHERE id=?", (request.form["status"], rid))
        flash(f"{r['name']}, {r['date']} at {r['time']}: marked {request.form['status'].replace('_', '-')}.")
    # show the booking's own day, so a confirmed booking for another day does not seem to disappear
    return redirect(url_for("admin_reservations", date=r["date"] if r else request.form.get("date")))


def save_photo(file):
    if not file or not file.filename:
        return None
    ext, head = Path(file.filename).suffix.lower(), file.stream.read(12)
    file.stream.seek(0)
    real = (head.startswith(b"\x89PNG") and ext == ".png") or (head.startswith(b"\xff\xd8\xff") and ext in (".jpg", ".jpeg")) \
        or (head[:4] == b"RIFF" and head[8:12] == b"WEBP" and ext == ".webp")
    if not real:
        raise ValueError("Photo must be a real PNG, JPG or WEBP file.")
    name = secrets.token_hex(8) + ext
    file.save(UPLOADS / name)
    return "/media/" + name


def drop_photo(path):
    """Delete an uploaded photo from disk once no dish, table, gallery item or logo uses it."""
    if not path or not path.startswith("/media/"):
        return
    used = db().execute("""SELECT 1 FROM dishes WHERE image=:p UNION ALL SELECT 1 FROM dining_tables WHERE image=:p
        UNION ALL SELECT 1 FROM gallery WHERE image=:p UNION ALL SELECT 1 FROM settings WHERE key='logo' AND value=:p""",
                        {"p": path}).fetchone()
    if not used:
        (UPLOADS / Path(path).name).unlink(missing_ok=True)  # .name keeps the delete inside the uploads folder


@app.get("/admin/menu")
@admin_required
def admin_menu():
    cats = db().execute("SELECT * FROM categories ORDER BY sort, id").fetchall()
    dishes = db().execute("SELECT d.*, c.name AS cat FROM dishes d JOIN categories c ON c.id=d.category_id ORDER BY c.sort, d.id").fetchall()
    edit = db().execute("SELECT * FROM dishes WHERE id=?", (request.args.get("edit", 0, type=int),)).fetchone()
    return render_template("admin_menu.html", tab="menu", cats=cats, dishes=dishes, edit=edit, icons=ICONS, diets=DIETS)


@app.post("/admin/menu/save")
@admin_required
def admin_dish_save():
    check_csrf()
    f, did = request.form, request.form.get("id", type=int)
    back = url_for("admin_menu", edit=did)
    try:
        cents = int(round(float(f.get("price", "")) * 100))
        if not 0 < cents < 10_000_000:
            raise ValueError
    except ValueError:
        flash("Price must be a number above 0, like 12.50.")
        return redirect(back)
    cat = db().execute("SELECT id FROM categories WHERE id=?", (f.get("category_id", type=int),)).fetchone()
    if not cat or not f.get("name", "").strip():
        flash("A dish needs a name and a category.")
        return redirect(back)
    old = db().execute("SELECT image FROM dishes WHERE id=?", (did,)).fetchone() if did else None
    try:
        image = save_photo(request.files.get("photo")) or (None if f.get("remove_photo") else (old["image"] if old else None))
    except ValueError as e:
        flash(str(e))
        return redirect(back)
    diet = ",".join(x for x in f.getlist("diet") if x in DIETS)
    vals = (cat["id"], f["name"].strip()[:100], f.get("description", "").strip()[:400], cents,
            f.get("tag", "").strip()[:30], image, 1 if f.get("featured") else 0, 1 if f.get("visible") else 0,
            f.get("ingredients", "").strip()[:300], diet, 1 if f.get("sold_out") else 0)
    if did and old:
        db().execute("UPDATE dishes SET category_id=?,name=?,description=?,price_cents=?,tag=?,image=?,featured=?,visible=?,ingredients=?,diet=?,sold_out=? WHERE id=?", vals + (did,))
    else:
        db().execute("INSERT INTO dishes(category_id,name,description,price_cents,tag,image,featured,visible,ingredients,diet,sold_out) VALUES(?,?,?,?,?,?,?,?,?,?,?)", vals)
    rid = did if (did and old) else db().execute("SELECT last_insert_rowid()").fetchone()[0]
    db().execute("UPDATE dishes SET name_ka=?, description_ka=?, ingredients_ka=? WHERE id=?",
                 (f.get("name_ka", "").strip()[:100], f.get("description_ka", "").strip()[:400], f.get("ingredients_ka", "").strip()[:300], rid))
    if old and old["image"] != image:
        drop_photo(old["image"])
    flash("Dish saved.")
    return redirect(url_for("admin_menu"))


@app.post("/admin/menu/delete/<int:did>")
@admin_required
def admin_dish_delete(did):
    check_csrf()
    old = db().execute("SELECT image FROM dishes WHERE id=?", (did,)).fetchone()
    db().execute("DELETE FROM dishes WHERE id=?", (did,))
    if old:
        drop_photo(old["image"])
    flash("Dish deleted.")
    return redirect(url_for("admin_menu"))


@app.post("/admin/categories/save")
@admin_required
def admin_category_save():
    check_csrf()
    f, cid = request.form, request.form.get("id", type=int)
    name, icon = f.get("name", "").strip()[:40], f.get("icon")
    if not name or icon not in ICONS:
        flash("A category needs a name and an icon.")
        return redirect(url_for("admin_menu"))
    sort, section = f.get("sort", 0, type=int), ("drinks" if f.get("section") == "drinks" else "food")
    if cid:
        db().execute("UPDATE categories SET name=?, icon=?, sort=?, section=? WHERE id=?", (name, icon, sort, section, cid))
    else:
        db().execute("INSERT INTO categories(name,icon,sort,section) VALUES(?,?,?,?)", (name, icon, sort or 99, section))
    rid = cid if cid else db().execute("SELECT last_insert_rowid()").fetchone()[0]
    db().execute("UPDATE categories SET name_ka=? WHERE id=?", (f.get("name_ka", "").strip()[:40], rid))
    flash("Category saved.")
    return redirect(url_for("admin_menu"))


@app.post("/admin/categories/delete/<int:cid>")
@admin_required
def admin_category_delete(cid):
    check_csrf()
    if db().execute("SELECT 1 FROM dishes WHERE category_id=?", (cid,)).fetchone():
        flash("Move or delete the dishes in this category first.")
    else:
        db().execute("DELETE FROM categories WHERE id=?", (cid,))
        flash("Category deleted.")
    return redirect(url_for("admin_menu"))


SETTING_FIELDS = [("name", "Cafe name", "text"), ("tagline", "Short tagline", "text"), ("about", "About text", "textarea"),
                  ("address", "Address", "text"), ("phone", "Phone", "text"), ("email", "Email", "text"),
                  ("currency", "Currency symbol", "text"), ("chat_greeting", "First message in the chat", "text"),
                  ("special", "Today's special (leave empty to hide)", "text"), ("instagram", "Instagram link (https://...)", "text"),
                  ("whatsapp", "WhatsApp number (digits, with country code)", "text"), ("google_reviews", "Google reviews link (https://...)", "text"),
                  ("color_dark", "Main dark color (header, footer)", "color"), ("color_accent", "Accent color (prices, steps)", "color"),
                  ("color_gold", "Highlight color (buttons)", "color"), ("font_style", "Font style", "choice"),
                  ("steps_count", "Story counter number (empty hides it)", "text"), ("steps_text", "Story counter text", "text"),
                  ("tagline_ka", "Georgian: short tagline", "text"), ("about_ka", "Georgian: about text", "textarea"),
                  ("special_ka", "Georgian: today's special", "text"), ("steps_text_ka", "Georgian: story counter text", "text"),
                  ("chat_greeting_ka", "Georgian: first chat message", "text")]


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        check_csrf()
        f, problems = request.form, []
        new_hours = []
        for d in range(7):
            o, c, closed = f.get(f"open{d}", ""), f.get(f"close{d}", ""), 1 if f.get(f"closed{d}") else 0
            try:
                if not closed and not mins(o) < mins(c) <= 24 * 60:
                    raise ValueError
                new_hours.append((o, c, closed, d))
            except ValueError:
                problems.append(DAYS[d])
        nums = {}
        for key, lo, hi in (("slot_minutes", 30, 300), ("max_days_ahead", 1, 365), ("max_group", 1, 40)):
            v = f.get(key, type=int)
            if v is None or not lo <= v <= hi:
                problems.append(key.replace("_", " "))
            nums[key] = str(v)
        if problems:
            flash("Please check: " + ", ".join(problems) + ".")
            return redirect(url_for("admin_settings"))
        try:
            new_logo = save_photo(request.files.get("logo"))
        except ValueError as e:
            flash(str(e))
            return redirect(url_for("admin_settings"))
        if new_logo or f.get("remove_logo"):
            old_logo = S()["logo"]
            db().execute("INSERT OR REPLACE INTO settings(key,value) VALUES('logo',?)", (new_logo or "",))
            if old_logo != new_logo:
                drop_photo(old_logo)
        for key, _, _ in SETTING_FIELDS:
            val = f.get(key, "").strip()[:600]
            if key in ("instagram", "google_reviews") and not val.startswith("https://"):
                val = ""
            if key == "whatsapp":
                val = re.sub(r"\D", "", val)
            if key.startswith("color_") and not re.fullmatch(r"#[0-9a-fA-F]{6}", val):
                val = DEFAULTS[key]
            if key == "font_style" and val not in ("classic", "modern"):
                val = "classic"
            if key == "steps_count":
                val = re.sub(r"\D", "", val)[:4]
            db().execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                         (key, val if (key.endswith("_ka") or key == "steps_count") else (val or DEFAULTS[key])))
        for key, val in nums.items():
            db().execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, val))
        db().execute("INSERT OR REPLACE INTO settings(key,value) VALUES('auto_confirm',?)", ("1" if f.get("auto_confirm") else "0",))
        for o, c, closed, d in new_hours:
            db().execute("UPDATE hours SET open=?, close=?, closed=? WHERE day=?", (o, c, closed, d))
        flash("Settings saved.")
        return redirect(url_for("admin_settings"))
    return render_template("admin_settings.html", tab="settings", fields=SETTING_FIELDS)


@app.route("/admin/gallery", methods=["GET", "POST"])
@admin_required
def admin_gallery():
    if request.method == "POST":
        check_csrf()
        try:
            path = save_photo(request.files.get("photo"))
        except ValueError as e:
            flash(str(e))
            return redirect(url_for("admin_gallery"))
        if path:
            db().execute("INSERT INTO gallery(image,caption,caption_ka) VALUES(?,?,?)", (path, request.form.get("caption", "").strip()[:120],
                         request.form.get("caption_ka", "").strip()[:120]))
            flash("Photo added.")
        else:
            flash("Choose a photo first.")
        return redirect(url_for("admin_gallery"))
    return render_template("admin_gallery.html", tab="gallery", photos=db().execute("SELECT * FROM gallery ORDER BY id").fetchall())


@app.post("/admin/gallery/<int:pid>/<action>")
@admin_required
def admin_gallery_action(pid, action):
    check_csrf()
    if action == "delete":
        old = db().execute("SELECT image FROM gallery WHERE id=?", (pid,)).fetchone()
        db().execute("DELETE FROM gallery WHERE id=?", (pid,))
        if old:
            drop_photo(old["image"])
    elif action == "cover":
        db().execute("INSERT OR REPLACE INTO settings(key,value) VALUES('cover',?)", (str(pid),))
    return redirect(url_for("admin_gallery"))


@app.route("/admin/reviews", methods=["GET", "POST"])
@admin_required
def admin_reviews():
    if request.method == "POST":
        check_csrf()
        f = request.form
        name, text, rating = f.get("name", "").strip()[:60], f.get("text", "").strip()[:500], f.get("rating", 0, type=int)
        if name and text and 1 <= rating <= 5:
            db().execute("INSERT INTO reviews(name,rating,text) VALUES(?,?,?)", (name, rating, text))
            flash("Review added.")
        else:
            flash("A review needs a name, a rating from 1 to 5 and some text.")
        return redirect(url_for("admin_reviews"))
    return render_template("admin_reviews.html", tab="reviews", reviews=db().execute("SELECT * FROM reviews ORDER BY id DESC").fetchall())


@app.post("/admin/reviews/<int:rid>/<action>")
@admin_required
def admin_review_action(rid, action):
    check_csrf()
    if action == "delete":
        db().execute("DELETE FROM reviews WHERE id=?", (rid,))
    elif action in ("show", "hide"):
        db().execute("UPDATE reviews SET visible=? WHERE id=?", (1 if action == "show" else 0, rid))
    return redirect(url_for("admin_reviews"))


# ---------- direct chat ----------
def chat_by_token(token):
    return db().execute("SELECT * FROM chats WHERE token=?", (token,)).fetchone() if token else None


@app.post("/api/chat/send")
def chat_send():
    data = request.get_json(silent=True) or {}
    body = str(data.get("body", "")).strip()[:500]
    if not body:
        return jsonify(error="Type a message first."), 400
    chat = chat_by_token(str(data.get("token", "")))
    if chat is None:
        if db().execute("SELECT COUNT(*) FROM chats WHERE created > datetime('now','-1 minute')").fetchone()[0] >= 20:
            return jsonify(error="Chat is busy. Please try again in a minute."), 429
        token = secrets.token_urlsafe(16)
        chat_id = db().execute("INSERT INTO chats(token,name) VALUES(?,?)", (token, "Guest")).lastrowid
    else:
        token, chat_id = chat["token"], chat["id"]
        if db().execute("SELECT COUNT(*) FROM chat_messages WHERE chat_id=? AND sender='visitor' AND created > datetime('now','-1 minute')", (chat_id,)).fetchone()[0] >= 10:
            return jsonify(error="Please slow down a little."), 429
    quiet = db().execute("SELECT COUNT(*) FROM chat_messages WHERE chat_id=? AND sender='visitor' AND seen=0", (chat_id,)).fetchone()[0] == 0
    db().execute("INSERT INTO chat_messages(chat_id,sender,body) VALUES(?,?,?)", (chat_id, "visitor", body))
    if quiet:
        notify(f"New chat message\n\"{body[:200]}\"\n{request.host_url}admin/chats")
    db().execute("UPDATE chats SET last_at=CURRENT_TIMESTAMP WHERE id=?", (chat_id,))
    return jsonify(token=token), 201


@app.get("/api/chat/messages")
def chat_messages():
    chat = chat_by_token(request.args.get("token", ""))
    if chat is None:
        return jsonify([])
    rows = db().execute("SELECT id, sender, body FROM chat_messages WHERE chat_id=? AND id>? ORDER BY id", (chat["id"], request.args.get("after", 0, type=int))).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/admin/chats")
@admin_required
def admin_chats():
    chats = db().execute("""SELECT c.*, (SELECT COUNT(*) FROM chat_messages m WHERE m.chat_id=c.id AND m.sender='visitor' AND m.seen=0) AS unread,
        (SELECT body FROM chat_messages m WHERE m.chat_id=c.id ORDER BY id DESC LIMIT 1) AS last FROM chats c ORDER BY last_at DESC LIMIT 100""").fetchall()
    chats = private(chats, "last")
    open_id = request.args.get("open", type=int)
    current = next((c for c in chats if c["id"] == open_id), None)
    msgs = []
    if current:
        if not session.get("demo"):  # a demo visitor must not mark the owner's messages as read
            db().execute("UPDATE chat_messages SET seen=1 WHERE chat_id=? AND sender='visitor'", (open_id,))
        msgs = private(db().execute("SELECT id, sender, body FROM chat_messages WHERE chat_id=? ORDER BY id", (open_id,)).fetchall(), "body")
    return render_template("admin_chats.html", tab="chats", chats=chats, current=current, msgs=msgs)


@app.get("/admin/api/chats/<int:cid>")
@admin_required
def admin_chat_poll(cid):
    rows = private(db().execute("SELECT id, sender, body FROM chat_messages WHERE chat_id=? AND id>? ORDER BY id", (cid, request.args.get("after", 0, type=int))).fetchall(), "body")
    if not session.get("demo"):
        db().execute("UPDATE chat_messages SET seen=1 WHERE chat_id=? AND sender='visitor'", (cid,))
    return jsonify([dict(r) for r in rows])


@app.post("/admin/chats/<int:cid>/reply")
@admin_required
def admin_chat_reply(cid):
    check_csrf()
    body = request.form.get("body", "").strip()[:1000]
    if body and db().execute("SELECT 1 FROM chats WHERE id=?", (cid,)).fetchone():
        db().execute("INSERT INTO chat_messages(chat_id,sender,body,seen) VALUES(?,?,?,1)", (cid, "admin", body))
        db().execute("UPDATE chats SET last_at=CURRENT_TIMESTAMP WHERE id=?", (cid,))
    return redirect(url_for("admin_chats", open=cid))


# ---------- events and gift voucher requests ----------
KINDS = {"event": "Birthday or private event", "voucher": "Gift voucher", "other": "Something else"}


@app.route("/events", methods=["GET", "POST"])
def events():
    error = done = None
    f = request.form
    if request.method == "POST" and not f.get("website"):
        name, phone, msg = f.get("name", "").strip()[:80], re.sub(r"[^\d+]", "", f.get("phone", "")), f.get("message", "").strip()[:1000]
        if not csrf_ok():
            error = EXPIRED
        elif too_many_tries():
            error = "Too many tries. Please wait 10 minutes."
        else:
            if len(name) < 2 or not 7 <= len(phone.replace("+", "")) <= 15 or not msg:
                error = "Please enter your name, a phone number and a short message."
            else:
                kind = f.get("kind") if f.get("kind") in KINDS else "other"
                db().execute("INSERT INTO enquiries(kind,name,phone,email,date,guests,message) VALUES(?,?,?,?,?,?,?)",
                             (kind, name, phone, f.get("email", "").strip()[:120], f.get("date", "")[:10], f.get("guests", "")[:6], msg))
                notify(f"New request: {KINDS[kind]}\n{name}, {phone}\n{msg[:300]}\n{request.host_url}admin/requests")
                done = True
    return render_template("events.html", error=error, done=done, kinds=KINDS, form=f if error else {})


@app.get("/admin/requests")
@admin_required
def admin_requests():
    rows = private(db().execute("SELECT * FROM enquiries ORDER BY id DESC LIMIT 200").fetchall(), "name", "phone", "email", "message")
    return render_template("admin_requests.html", tab="requests", rows=rows, kinds=KINDS)


@app.post("/admin/requests/<int:eid>/<action>")
@admin_required
def admin_request_action(eid, action):
    check_csrf()
    if action == "delete":
        db().execute("DELETE FROM enquiries WHERE id=?", (eid,))
    elif action in ("new", "done"):
        db().execute("UPDATE enquiries SET status=? WHERE id=?", (action, eid))
    return redirect(url_for("admin_requests"))


# ---------- tables (photos, inside / outside) ----------
@app.get("/admin/tables")
@admin_required
def admin_tables():
    rows = db().execute("SELECT * FROM dining_tables ORDER BY id").fetchall()
    edit = db().execute("SELECT * FROM dining_tables WHERE id=?", (request.args.get("edit", 0, type=int),)).fetchone()
    return render_template("admin_tables.html", tab="tables", rows=rows, edit=edit)


@app.post("/admin/tables/save")
@admin_required
def admin_table_save():
    check_csrf()
    f, tid = request.form, request.form.get("id", type=int)
    name, seats = f.get("name", "").strip()[:60], f.get("seats", type=int)
    back = url_for("admin_tables", edit=tid)
    if not name or seats is None or not 1 <= seats <= 20:
        flash("A table needs a name and a number of seats from 1 to 20.")
        return redirect(back)
    old = db().execute("SELECT image FROM dining_tables WHERE id=?", (tid,)).fetchone() if tid else None
    try:
        image = save_photo(request.files.get("photo")) or (None if f.get("remove_photo") else (old["image"] if old else None))
    except ValueError as e:
        flash(str(e))
        return redirect(back)
    vals = (name, "outside" if f.get("zone") == "outside" else "inside", seats, image, f.get("description", "").strip()[:300],
            f.get("name_ka", "").strip()[:60], f.get("description_ka", "").strip()[:300], 1 if f.get("active") else 0)
    if tid and old:
        db().execute("UPDATE dining_tables SET name=?,zone=?,seats=?,image=?,description=?,name_ka=?,description_ka=?,active=? WHERE id=?", vals + (tid,))
    else:
        db().execute("INSERT INTO dining_tables(name,zone,seats,image,description,name_ka,description_ka,active) VALUES(?,?,?,?,?,?,?,?)", vals)
    if old and old["image"] != image:
        drop_photo(old["image"])
    flash("Table saved.")
    return redirect(url_for("admin_tables"))


@app.post("/admin/tables/<int:tid>/delete")
@admin_required
def admin_table_delete(tid):
    check_csrf()
    if db().execute("SELECT 1 FROM reservations WHERE ','||tables||',' LIKE ?", (f"%,{tid},%",)).fetchone():
        flash("This table is in the booking history. Switch it off instead of deleting it.")
    else:
        old = db().execute("SELECT image FROM dining_tables WHERE id=?", (tid,)).fetchone()
        db().execute("DELETE FROM dining_tables WHERE id=?", (tid,))
        if old:
            drop_photo(old["image"])
        flash("Table deleted.")
    return redirect(url_for("admin_tables"))


init_db()

if __name__ == "__main__":
    if ADMIN_PASSWORD == "admin123":
        print("WARNING: using the default admin password. Set ADMIN_PASSWORD before going online.")
    app.run(debug=True)
