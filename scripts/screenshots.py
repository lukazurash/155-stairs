"""Take the README screenshots.

Starts the site on a throwaway demo database (your real data/ is not touched),
adds some sample bookings, reviews and a chat, then saves PNGs to docs/screenshots/.

    pip install playwright
    python scripts/screenshots.py

Uses Microsoft Edge that is already installed, so no browser download is needed.
Set BROWSER=chrome to use Google Chrome instead.
"""
import os
import sqlite3
import sys
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
TMP = Path(tempfile.mkdtemp(prefix="155-stairs-shots-"))
os.environ.update(DB_PATH=str(TMP / "demo.db"), UPLOAD_DIR=str(TMP / "uploads"))
os.environ.pop("PRODUCTION", None)
os.environ.pop("ADMIN_PASSWORD", None)
sys.path.insert(0, str(ROOT))

import app as cafe  # noqa: E402  (after the environment is set)
from playwright.sync_api import sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

PORT = 5077
BASE = f"http://127.0.0.1:{PORT}"
TOMORROW = (datetime.now(ZoneInfo("Asia/Tbilisi")).date() + timedelta(days=1)).isoformat()


def seed():
    con = sqlite3.connect(cafe.DB_PATH)
    bookings = [  # name, phone, time, guests, tables, status, notes
        ("Nino K.", "+995555100200", "12:00", 2, "1", "confirmed", ""),
        ("Giorgi M.", "+995555100201", "13:00", 4, "2", "confirmed", "Window seat if possible"),
        ("Anna & Luka", "+995555100202", "18:00", 2, "3", "pending", "Anniversary dinner"),
        ("Tamar B.", "+995555100203", "18:00", 7, "4,5", "pending", "Birthday, bringing a cake"),
        ("Walk-in", "", "19:30", 3, "1", "confirmed", ""),
    ]
    for i, (name, phone, time, guests, tables, status, notes) in enumerate(bookings):
        con.execute("INSERT INTO reservations(ref,name,phone,date,time,guests,table_no,tables,notes,status,source) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (f"155-DEMO0{i}", name, phone, TOMORROW, time, guests,
                                                      int(tables.split(",")[0]), tables, notes, status,
                                                      "staff" if name == "Walk-in" else "web"))
    con.executemany("INSERT INTO reviews(name,rating,text,sample) VALUES(?,?,?,1)", [
        ("Mariam", 5, "Worth every one of the steps. The honey cake is the best in town."),
        ("David", 5, "Quiet, warm and friendly. Perfect for a long coffee and a book."),
        ("Elene", 4, "Lovely khachapuri and a great view from the terrace."),
    ])
    con.execute("UPDATE settings SET value='Pumpkin soup with roasted walnuts' WHERE key='special'")
    con.execute("UPDATE settings SET value='გოგრის წვნიანი შემწვარი ნიგვზით' WHERE key='special_ka'")
    con.execute("UPDATE settings SET value='მყუდრო კაფე კიბის თავზე.' WHERE key='tagline_ka'")
    con.execute("UPDATE dining_tables SET description='By the window, view over the old town' WHERE id=2")
    con.execute("UPDATE dining_tables SET description='On the terrace under the vines' WHERE id=4")
    chat = con.execute("INSERT INTO chats(token,name) VALUES('demo-chat','Guest')").lastrowid
    con.executemany("INSERT INTO chat_messages(chat_id,sender,body,seen) VALUES(?,?,?,?)", [
        (chat, "visitor", "Hi! Do you have a high chair for a toddler?", 1),
        (chat, "admin", "Hello! Yes, we have two. I'll put one by your table.", 1),
        (chat, "visitor", "Great, thank you! See you on Saturday.", 0),
    ])
    con.commit()
    con.close()


def main():
    seed()
    server = make_server("127.0.0.1", PORT, cafe.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    OUT.mkdir(parents=True, exist_ok=True)
    channel = "chrome" if os.environ.get("BROWSER") == "chrome" else "msedge"

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=channel)
        desk = browser.new_context(viewport={"width": 1280, "height": 800}, device_scale_factor=1)
        page = desk.new_page()

        def shot(name, full=False, clip_height=None):
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready")
            page.mouse.move(0, 0)
            kw = {"full_page": True, "clip": {"x": 0, "y": 0, "width": 1280, "height": clip_height}} if clip_height \
                else {"full_page": full}
            page.screenshot(path=str(OUT / f"{name}.png"), **kw)
            print("saved", OUT / f"{name}.png")

        page.goto(BASE + "/")
        shot("home")

        page.goto(BASE + "/menu")
        shot("menu", clip_height=1100)

        page.goto(BASE + "/reserve")
        page.click(f'[data-date="{TOMORROW}"]')  # the "Tomorrow" button
        page.click('label.pick:has(input[name=guests][value="4"])')
        page.wait_for_selector('#times input[value="18:00"]', state="attached")  # radios are visually hidden
        page.click('#times label:has(input[value="18:00"])')
        page.wait_for_selector("#tablelist .tcard:has(input[value='2'])")
        page.click("#tablelist .tcard:has(input[value='2'])")
        page.fill("input[name=name]", "Nino")
        page.fill("input[name=phone]", "+995 555 123 456")
        page.locator("h2.step").first.scroll_into_view_if_needed()
        shot("booking", full=True)

        page.goto(BASE + "/admin/login")
        page.fill("input[name=password]", "admin123")  # demo database only
        page.press("input[name=password]", "Enter")
        page.goto(f"{BASE}/admin/reservations?date={TOMORROW}")
        shot("admin", clip_height=1000)

        page.goto(BASE + "/admin/chats?open=1")
        shot("admin-chat")

        phone = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True,
                                    has_touch=True)
        phone.add_cookies([{"name": "lang", "value": "ka", "url": BASE}])
        page = phone.new_page()
        page.goto(BASE + "/")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(OUT / "mobile-ka.png"))
        print("saved", OUT / "mobile-ka.png")
        browser.close()
    server.shutdown()


if __name__ == "__main__":
    main()
