"""Georgian content, link previews, robots/sitemap, the 404 page and HSTS."""
import io

import app as cafe
from conftest import csrf, sql
from test_demo_content import demo

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def georgian(client):
    client.set_cookie("lang", "ka")
    return client


def test_georgian_pages_show_georgian_content(client):
    demo.fill(cafe.DB_PATH)
    georgian(client)
    menu = client.get("/menu").data.decode()
    assert "ფხალის ტრიო" in menu and "წასახემსებლები" in menu and "Pkhali trio" not in menu and "Starters" not in menu
    drinks = client.get("/drinks").data.decode()
    assert "სახლის თეთრი ღვინო (ჭიქა)" in drinks and "Rkatsiteli" not in drinks
    home = client.get("/").data.decode()
    assert "საღამოები კიბის თავზე" in home and "Evenings at the top" not in home
    assert "აიარეთ 155 საფეხური" in home
    tables = client.get("/api/tables?date=" + __import__("conftest").day(1) + "&time=12:00").json
    assert tables[0]["name"].startswith("მაგიდა") and "Table" not in tables[0]["description"]


def test_english_pages_stay_english(client):
    demo.fill(cafe.DB_PATH)
    menu = client.get("/menu").data.decode()
    assert "Pkhali trio" in menu and "ფხალის" not in menu


def test_gallery_takes_a_georgian_caption(admin):
    admin.post("/admin/gallery", data={"photo": (io.BytesIO(PNG), "a.png"), "caption": "Our stairs",
                                       "caption_ka": "ჩვენი კიბე", "csrf": csrf(admin)}, content_type="multipart/form-data")
    assert sql("SELECT caption, caption_ka FROM gallery")[0][:] == ("Our stairs", "ჩვენი კიბე")


def test_link_preview_tags(client):
    demo.fill(cafe.DB_PATH)
    html = client.get("/menu").data.decode()
    assert '<meta name="description" content="Climb the 155 steps' in html
    assert '<meta property="og:title" content="Menu - 155 Stairs">' in html
    assert '<meta property="og:image" content="http://localhost/static/demo/cafe-evening.jpg">' in html


def test_robots_and_sitemap(client):
    robots = client.get("/robots.txt")
    assert robots.status_code == 200 and b"Disallow: /admin" in robots.data and b"sitemap.xml" in robots.data
    site = client.get("/sitemap.xml").data.decode()
    assert site.count("<url>") == len(cafe.PUBLIC_PAGES) and "/admin" not in site


def test_styled_404_page(client):
    resp = client.get("/no-such-page")
    assert resp.status_code == 404 and b"This step does not exist" in resp.data and b"Reserve a table" in resp.data
    assert "ეს საფეხური არ არსებობს" in georgian(client).get("/no-such-page").data.decode()
    api = client.get("/api/nothing")
    assert api.status_code == 404 and api.json == {"error": "Not found."}


def test_hsts_only_in_production(client, monkeypatch):
    assert "Strict-Transport-Security" not in client.get("/").headers
    monkeypatch.setattr(cafe, "PRODUCTION", True)
    assert client.get("/").headers["Strict-Transport-Security"] == "max-age=31536000"
