"""scripts/demo_content.py fills an empty site, is safe to repeat and never replaces the owner's content."""
import importlib.util
import re
from pathlib import Path

import app as cafe
from conftest import sql

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("demo_content", ROOT / "scripts" / "demo_content.py")
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)


def test_fills_an_empty_site():
    report = demo.fill(cafe.DB_PATH)
    assert report == {"dish photos": 13, "gallery photos": 6, "table photos": 5, "reviews": 3, "texts": 3}
    cover = sql("SELECT value FROM settings WHERE key='cover'")[0]["value"]
    assert cover == str(sql("SELECT MIN(id) AS i FROM gallery")[0]["i"])


def test_running_twice_adds_nothing_more():
    demo.fill(cafe.DB_PATH)
    assert set(demo.fill(cafe.DB_PATH).values()) == {0}
    assert len(sql("SELECT * FROM gallery")) == 6 and len(sql("SELECT * FROM reviews")) == 3


def test_owner_content_is_kept():
    sql("UPDATE dishes SET image='/media/mine.jpg' WHERE name='Espresso'")
    sql("INSERT INTO reviews(name,rating,text) VALUES('Real guest',5,'Great!')")
    sql("UPDATE settings SET value='Owner special' WHERE key='special'")
    demo.fill(cafe.DB_PATH)
    assert sql("SELECT image FROM dishes WHERE name='Espresso'")[0]["image"] == "/media/mine.jpg"
    assert [r["name"] for r in sql("SELECT name FROM reviews")] == ["Real guest"]
    assert sql("SELECT value FROM settings WHERE key='special'")[0]["value"] == "Owner special"


def test_pages_show_the_photos_and_every_file_exists(client):
    demo.fill(cafe.DB_PATH)
    html = b"".join(client.get(p).data for p in ("/", "/menu", "/drinks")).decode()
    used = set(re.findall(r'/static/demo/[\w-]+\.jpg', html))
    assert len(used) >= 15
    for path in used:
        assert client.get(path).status_code == 200, path
    assert "What our guests say" in html and "Pumpkin soup" in html


def test_demo_photos_are_never_deleted_from_disk(admin):
    """Removing a demo photo in the admin must not delete the file from the repo (only /media/ uploads are cleaned up)."""
    from conftest import csrf
    demo.fill(cafe.DB_PATH)
    gid = sql("SELECT id FROM gallery ORDER BY id LIMIT 1")[0]["id"]
    admin.post(f"/admin/gallery/{gid}/delete", data={"csrf": csrf(admin)})
    assert (ROOT / "static" / "demo" / "cafe-evening.jpg").is_file()
