"""Fill the site with demo content: dish photos, gallery, table photos, sample reviews and a special.

    python scripts/demo_content.py                 # uses data/cafe.db
    DB_PATH=/path/to/cafe.db python scripts/demo_content.py

Safe to run more than once, and on a site that is already in use: it only fills things that are
still empty, so photos, reviews and text you added yourself are never replaced.
The photos live in static/demo/ (see static/demo/CREDITS.md).
"""
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = "/static/demo/"

DISH_PHOTOS = {  # dish name (as seeded) -> file in static/demo
    "Pkhali trio": "pkhali", "Chicken in walnut sauce": "satsivi", "Tomato bruschetta": "bruschetta", "Adjarian khachapuri": "khachapuri", "Mushroom pasta": "mushroom-pasta",
    "Honey cake": "honey-cake", "Baked cheesecake": "cheesecake", "Espresso": "espresso", "Cappuccino": "cappuccino",
    "Hot chocolate": "hot-chocolate", "Homemade lemonade": "lemonade", "Iced coffee": "iced-coffee",
    "House red wine (glass)": "red-wine", "House white wine (glass)": "white-wine", "Craft beer": "craft-beer",
}
GALLERY = [  # first one becomes the cover photo on the home page
    ("cafe-evening", "Evenings at the top of the stairs"),
    ("khachapuri-tbilisi", "Adjarian khachapuri, straight from the oven"),
    ("cafe-lights", "Warm light and old frames"),
    ("khinkali-table", "Khinkali night with friends"),
    ("cafe-red-wall", "Our quiet corner"),
    ("terrace-courtyard", "The courtyard in summer"),
]
TABLES = {  # table id -> (photo, description)
    1: ("table-corner", "A quiet corner table, good for two"),
    2: ("table-window", "By the window, with afternoon sun"),
    3: ("table-green-chairs", "Bright table near the big windows"),
    4: ("terrace-courtyard", "On the courtyard terrace"),
    5: ("terrace-chairs", "Terrace table, open air"),
}
REVIEWS = [  # sample reviews for the demo (marked sample=1)
    ("Mariam", 5, "Worth every one of the steps. The honey cake is the best I've had in Tbilisi."),
    ("David", 5, "Quiet, warm and friendly. Perfect for a long coffee and a book by the window."),
    ("Elene", 4, "Lovely khachapuri and a beautiful courtyard. Book ahead on weekends!"),
]
SETTINGS = {  # only set when still empty
    "special": "Pumpkin soup with roasted walnuts",
    "special_ka": "გოგრის წვნიანი შემწვარი ნიგვზით",
    "tagline_ka": "მყუდრო კაფე კიბის თავზე.",
}


def fill(db_path):
    """Add the demo content to the database at db_path and return a short report."""
    missing = [n for n in list(DISH_PHOTOS.values()) + [g for g, _ in GALLERY] + [t for t, _ in TABLES.values()]
               if not (ROOT / "static" / "demo" / f"{n}.jpg").is_file()]
    if missing:
        raise SystemExit(f"Missing photos in static/demo: {', '.join(missing)}")
    con = sqlite3.connect(db_path)
    try:
        report = {}
        n = 0
        for name, photo in DISH_PHOTOS.items():
            n += con.execute("UPDATE dishes SET image=? WHERE name=? AND COALESCE(image,'')=''",
                             (DEMO + photo + ".jpg", name)).rowcount
        report["dish photos"] = n

        n = 0
        if con.execute("SELECT COUNT(*) FROM gallery").fetchone()[0] == 0:
            for photo, caption in GALLERY:
                con.execute("INSERT INTO gallery(image,caption) VALUES(?,?)", (DEMO + photo + ".jpg", caption))
                n += 1
            first = con.execute("SELECT MIN(id) FROM gallery").fetchone()[0]
            con.execute("UPDATE settings SET value=? WHERE key='cover' AND value=''", (str(first),))
        report["gallery photos"] = n

        n = 0
        for tid, (photo, text) in TABLES.items():
            n += con.execute("UPDATE dining_tables SET image=? WHERE id=? AND COALESCE(image,'')=''",
                             (DEMO + photo + ".jpg", tid)).rowcount
            con.execute("UPDATE dining_tables SET description=? WHERE id=? AND description=''", (text, tid))
        report["table photos"] = n

        n = 0
        if con.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0:
            con.executemany("INSERT INTO reviews(name,rating,text,sample) VALUES(?,?,?,1)", REVIEWS)
            n = len(REVIEWS)
        report["reviews"] = n

        n = 0
        for key, value in SETTINGS.items():
            n += con.execute("UPDATE settings SET value=? WHERE key=? AND value=''", (value, key)).rowcount
        report["texts"] = n
        con.commit()
        return report
    finally:
        con.close()


if __name__ == "__main__":
    db = Path(os.environ.get("DB_PATH", ROOT / "data" / "cafe.db"))
    if not db.is_file():
        sys.exit(f"No database at {db}. Open the site once first (it creates the database), then run this again.")
    for what, count in fill(db).items():
        print(f"{what:15} {count} added")
    print("Done. Reload the web app to see it (on PythonAnywhere: the green Reload button).")
