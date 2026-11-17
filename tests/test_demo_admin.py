"""The read-only demo admin: off unless DEMO_ADMIN=1, changes nothing, hides guests' details."""
import pytest

import app as cafe
from conftest import book, csrf, day, login, sql


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setattr(cafe, "DEMO_ADMIN", True)


def demo_login(client):
    return client.post("/admin/demo", data={"csrf": csrf(client)})


@pytest.fixture
def guest_data(client):
    """A real-looking booking, request and chat, as a live site would have."""
    book(client, name="Nino Beridze", phone="+995 555 123 456", email="nino@example.com", notes="Window seat for Nino")
    sql("INSERT INTO enquiries(kind,name,phone,email,message) VALUES('event','Giorgi','+995555999888','g@example.com','Party for 20')")
    sql("INSERT INTO chats(token,name) VALUES('t1','Guest')")
    sql("INSERT INTO chat_messages(chat_id,sender,body) VALUES(1,'visitor','My number is 555 777 888')")


def test_demo_is_off_by_default(client):
    assert b"read-only demo" not in client.get("/admin/login").data
    assert demo_login(client).status_code == 404
    assert client.get("/admin/reservations").status_code == 302


def test_demo_login_opens_the_admin(client, demo_on):
    assert b"Look around (read-only demo)" in client.get("/admin/login").data
    resp = demo_login(client)
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/admin/reservations")
    for path in ["/admin/reservations", "/admin/menu", "/admin/tables", "/admin/gallery", "/admin/reviews",
                 "/admin/requests", "/admin/chats", "/admin/closures", "/admin/settings"]:
        page = client.get(path)
        assert page.status_code == 200 and b"Read-only demo" in page.data, path


def test_demo_can_change_nothing(client, demo_on, guest_data):
    demo_login(client)
    token = csrf(client)
    rid = sql("SELECT id FROM reservations")[0]["id"]
    before = [sql(f"SELECT * FROM {t}") for t in ("reservations", "dishes", "settings", "closures", "chat_messages", "dining_tables")]
    posts = [
        (f"/admin/reservations/{rid}/status", {"status": "cancelled"}),
        ("/admin/reservations/new", {"date": day(1), "time": "12:00", "guests": "2"}),
        ("/admin/menu/delete/1", {}),
        ("/admin/closures", {"date": day(1), "whole": "1"}),
        ("/admin/password", {"current": "admin123", "new": "taken-over-123", "again": "taken-over-123"}),
        ("/admin/settings", {"name": "Hacked"}),
        ("/admin/chats/1/reply", {"body": "spam"}),
        ("/admin/tables/1/delete", {}),
    ]
    for path, form in posts:
        resp = client.post(path, data={**form, "csrf": token})
        assert resp.status_code == 302, path
    assert [sql(f"SELECT * FROM {t}") for t in ("reservations", "dishes", "settings", "closures", "chat_messages", "dining_tables")] == before
    assert b"nothing was changed" in client.get("/admin/reservations").data


def test_demo_hides_guest_details(client, demo_on, guest_data):
    demo_login(client)
    pages = (client.get(f"/admin/reservations?date={day(1)}").data + client.get("/admin/requests").data
             + client.get("/admin/chats?open=1").data + client.get("/admin/api/chats/1").data).decode()
    for secret in ("Nino Beridze", "555123456", "nino@example.com", "Window seat for Nino", "Giorgi", "g@example.com",
                   "Party for 20", "555 777 888"):
        assert secret not in pages, secret
    assert "N•••" in pages and "+995 ••• ••• 56" in pages


def test_demo_does_not_mark_chats_read(client, demo_on, guest_data):
    demo_login(client)
    client.get("/admin/chats?open=1")
    client.get("/admin/api/chats/1")
    assert sql("SELECT seen FROM chat_messages")[0]["seen"] == 0


def test_demo_cannot_open_guests_confirmation_pages(client, demo_on, guest_data):
    ref = sql("SELECT ref FROM reservations")[0]["ref"]
    visitor = cafe.app.test_client()
    demo_login(visitor)
    assert visitor.get(f"/reserved/{ref}").headers["Location"].endswith("/manage")


def test_owner_still_sees_everything(client, demo_on, guest_data):
    login(client)
    page = client.get(f"/admin/reservations?date={day(1)}").data.decode()
    assert "Nino Beridze" in page and "Read-only demo" not in page
    client.get("/admin/chats?open=1")
    assert sql("SELECT seen FROM chat_messages")[0]["seen"] == 1


def test_demo_can_log_out_and_owner_can_log_in(client, demo_on):
    demo_login(client)
    client.post("/admin/logout", data={"csrf": csrf(client)})
    assert client.get("/admin/reservations").status_code == 302
    login(client)
    with client.session_transaction() as s:
        assert s.get("admin") and not s.get("demo")
