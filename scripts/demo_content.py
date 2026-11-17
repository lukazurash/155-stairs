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
    "about_ka": "აიარეთ 155 საფეხური და იპოვით პატარა, თბილ ადგილს კარგი ყავით, სახლის დესერტებითა და გემრიელი "
                "კერძებით. შემოიარეთ სწრაფი ესპრესოსთვის ან დარჩით მთელი საღამო.",
    "steps_text_ka": "საფეხური მშვიდ კუთხემდე, სადაც კარგი ყავა, თბილი შუქი და სახლის საჭმელი გელით.",
    "chat_greeting_ka": "გამარჯობა! მოგვწერეთ ნებისმიერი კითხვა, ან გვითხარით დაბადების დღის თუ სხვა განსაკუთრებული დღის შესახებ.",
}
# Georgian text, filled only where the Georgian field is still empty. Please have a native speaker proofread.
DISH_KA = {  # English name -> (name, description, ingredients)
    "Pkhali trio": ("ფხალის ტრიო", "ისპანახის, ჭარხლისა და მწვანე ლობიოს ფხალი ნიგვზითა და ბროწეულით.",
                    "ისპანახი, ჭარხალი, მწვანე ლობიო, ნიგოზი, ნიორი, ბროწეული"),
    "Tomato bruschetta": ("ბრუსკეტა პომიდვრით", "შემწვარი პური, მწიფე პომიდორი, რეჰანი და ზეითუნის ზეთი.",
                          "საფუვრიანი პური, პომიდორი, რეჰანი, ნიორი, ზეითუნის ზეთი"),
    "Adjarian khachapuri": ("აჭარული ხაჭაპური", "ცხელი ყველიანი პური თხიერი კვერცხითა და კარაქით.",
                            "ცომი, სულგუნი, კვერცხის გული, კარაქი"),
    "Chicken in walnut sauce": ("საცივი", "ნაზი ქათამი ნიგვზისა და მწვანილის სოუსში.",
                                "ქათამი, ნიგოზი, ნიორი, ქინძი, უცხო სუნელი"),
    "Mushroom pasta": ("პასტა სოკოთი", "ახალი პასტა ტყის სოკოთი და ნაღებით.",
                       "ახალი პასტა, ტყის სოკო, ნაღები, პარმეზანი, ბეგქონდარა"),
    "Honey cake": ("თაფლის ნამცხვარი", "თაფლის ბისკვიტის ფენები ნაზი კრემით.", "თაფლი, ფქვილი, არაჟანი, ნიგოზი"),
    "Baked cheesecake": ("გამომცხვარი ჩიზქეიქი", "ნაზი ჩიზქეიქი კენკრის სოუსით.",
                         "ნაღების ყველი, კვერცხი, ორცხობილის ფუძე, კენკრა"),
    "Espresso": ("ესპრესო", "მდიდარი გემოს, მოკლე.", "ერთი წარმოშობის ყავის მარცვალი"),
    "Cappuccino": ("კაპუჩინო", "ესპრესო რძის ნაზი ქაფით.", "ესპრესო, ათბობილი რძე"),
    "Hot chocolate": ("ცხელი შოკოლადი", "სქელი, მუქი და გამათბობელი.", "მუქი შოკოლადი, რძე, კაკაო"),
    "Homemade lemonade": ("სახლის ლიმონათი", "ახალი ლიმონი, პიტნა და ცოტა თაფლი.", "ლიმონი, პიტნა, თაფლი, გაზიანი წყალი"),
    "Iced coffee": ("ცივი ყავა", "ცივი ესპრესო ყინულზე, რძით.", "ესპრესო, რძე, ყინული"),
    "House red wine (glass)": ("სახლის წითელი ღვინო (ჭიქა)", "ქართული წითელი, რბილი და მშრალი.", "საფერავი"),
    "House white wine (glass)": ("სახლის თეთრი ღვინო (ჭიქა)", "ქართული თეთრი, ცოცხალი და ხილის არომატით.", "რქაწითელი"),
    "Craft beer": ("ხელნაკეთი ლუდი", "ადგილობრივი ხელნაკეთი ლუდი, იკითხეთ დღევანდელი არჩევანი.", "ალაო, სვია, წყალი, საფუარი"),
}
CATEGORY_KA = {"Starters": "წასახემსებლები", "Main dishes": "ძირითადი კერძები", "Desserts": "დესერტები",
               "Hot drinks": "ცხელი სასმელები", "Cold drinks": "ცივი სასმელები", "Alcoholic drinks": "ალკოჰოლური სასმელები"}
GALLERY_KA = {
    "Evenings at the top of the stairs": "საღამოები კიბის თავზე",
    "Adjarian khachapuri, straight from the oven": "აჭარული ხაჭაპური, პირდაპირ ღუმელიდან",
    "Warm light and old frames": "თბილი შუქი და ძველი ჩარჩოები",
    "Khinkali night with friends": "ხინკლის საღამო მეგობრებთან",
    "Our quiet corner": "ჩვენი მყუდრო კუთხე",
    "The courtyard in summer": "ეზო ზაფხულში",
}
TABLE_KA = {1: "მყუდრო კუთხის მაგიდა, ორისთვის იდეალური", 2: "ფანჯარასთან, შუადღის მზით", 3: "ნათელი მაგიდა დიდ ფანჯრებთან",
            4: "ეზოს ტერასაზე", 5: "ტერასის მაგიდა, ღია ცის ქვეშ"}


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

        if "caption_ka" not in [c[1] for c in con.execute("PRAGMA table_info(gallery)")]:  # site not reloaded yet
            con.execute("ALTER TABLE gallery ADD COLUMN caption_ka TEXT NOT NULL DEFAULT ''")
        n = 0
        for name, (n_ka, d_ka, i_ka) in DISH_KA.items():
            n += con.execute("""UPDATE dishes SET name_ka=CASE WHEN name_ka='' THEN ? ELSE name_ka END,
                description_ka=CASE WHEN description_ka='' THEN ? ELSE description_ka END,
                ingredients_ka=CASE WHEN ingredients_ka='' THEN ? ELSE ingredients_ka END
                WHERE name=? AND (name_ka='' OR description_ka='' OR ingredients_ka='')""", (n_ka, d_ka, i_ka, name)).rowcount
        for name, ka in CATEGORY_KA.items():
            n += con.execute("UPDATE categories SET name_ka=? WHERE name=? AND name_ka=''", (ka, name)).rowcount
        for caption, ka in GALLERY_KA.items():
            n += con.execute("UPDATE gallery SET caption_ka=? WHERE caption=? AND caption_ka=''", (ka, caption)).rowcount
        for tid, ka in TABLE_KA.items():
            n += con.execute("UPDATE dining_tables SET description_ka=? WHERE id=? AND description_ka='' AND description<>''",
                             (ka, tid)).rowcount
            n += con.execute("UPDATE dining_tables SET name_ka=? WHERE id=? AND name_ka='' AND name=?",
                             (f"მაგიდა {tid}", tid, f"Table {tid}")).rowcount
        report["georgian texts"] = n
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
