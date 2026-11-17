"""Security fixes: CSRF, private confirmation page, rate limits, admin login, uploads."""
import io

import pytest

import app as cafe
from conftest import book, csrf, day, login, sql

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\0" * 32


def ref_of_only_booking():
    return sql("SELECT ref FROM reservations")[0]["ref"]


# ---------- CSRF on public forms ----------
@pytest.mark.parametrize("path, form", [
    ("/reserve", {"name": "Nino", "phone": "+995555123456", "date": day(1), "time": "12:00", "guests": "2", "tables": "1"}),
    ("/manage", {"ref": "155-ABCDEF", "phone": "+995555123456"}),
    ("/manage/cancel", {"ref": "155-ABCDEF", "phone": "+995555123456"}),
    ("/admin/login", {"password": "admin123"}),
])
def test_public_forms_reject_missing_or_wrong_csrf(client, path, form):
    client.get("/reserve")  # the browser has a token, but the form does not send it
    assert client.post(path, data=form).status_code == 400
    assert client.post(path, data={**form, "csrf": "wrong"}).status_code == 400


def test_booking_without_csrf_saves_nothing(client):
    client.post("/reserve", data={"name": "Nino", "phone": "+995555123456", "date": day(1), "time": "12:00",
                                  "guests": "2", "tables": "1"})
    assert sql("SELECT * FROM reservations") == []


def test_events_form_requires_csrf(client):
    form = {"name": "Nino", "phone": "+995555123456", "message": "Birthday for 10", "kind": "event"}
    resp = client.post("/events", data=form)
    assert b"open for too long" in resp.data
    assert sql("SELECT * FROM enquiries") == []
    client.post("/events", data={**form, "csrf": csrf(client)})
    assert len(sql("SELECT * FROM enquiries")) == 1


# ---------- private confirmation page ----------
def test_confirmation_page_only_for_the_booking_browser(client):
    book(client)
    ref = ref_of_only_booking()
    assert client.get(f"/reserved/{ref}").status_code == 200

    stranger = cafe.app.test_client()
    resp = stranger.get(f"/reserved/{ref}")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/manage")


def test_admin_can_open_any_confirmation_page(client):
    book(client)
    ref = ref_of_only_booking()
    owner = cafe.app.test_client()
    login(owner)
    assert owner.get(f"/reserved/{ref}").status_code == 200


# ---------- booking lookup and cancel ----------
def test_lookup_needs_matching_phone(client):
    book(client)
    ref = ref_of_only_booking()
    token = csrf(client)
    wrong = client.post("/manage", data={"ref": ref, "phone": "+995 555 999 999", "csrf": token})
    assert b"could not find" in wrong.data
    right = client.post("/manage", data={"ref": ref.lower(), "phone": "+995 555 123 456", "csrf": token})
    assert ref.encode() in right.data and b"could not find" not in right.data


def test_cancel_with_wrong_phone_does_nothing(client):
    book(client)
    ref = ref_of_only_booking()
    client.post("/manage/cancel", data={"ref": ref, "phone": "+995555999999", "csrf": csrf(client)})
    assert sql("SELECT status FROM reservations")[0]["status"] == "pending"


def test_guest_can_cancel_own_booking(client, notifications):
    book(client)
    ref = ref_of_only_booking()
    client.post("/manage/cancel", data={"ref": ref, "phone": "+995555123456", "csrf": csrf(client)})
    assert sql("SELECT status FROM reservations")[0]["status"] == "cancelled"
    assert "cancelled" in notifications[-1]


def test_arrived_booking_cannot_be_cancelled_online(client):
    book(client)
    sql("UPDATE reservations SET status='arrived'")
    resp = client.post("/manage/cancel", data={"ref": ref_of_only_booking(), "phone": "+995555123456", "csrf": csrf(client)})
    assert b"can no longer be cancelled" in resp.data
    assert sql("SELECT status FROM reservations")[0]["status"] == "arrived"


@pytest.mark.parametrize("path", ["/manage", "/manage/cancel"])
def test_lookup_and_cancel_are_rate_limited(client, path):
    token = csrf(client)
    for _ in range(10):
        assert client.post(path, data={"ref": "155-000000", "phone": "+995555123456", "csrf": token}).status_code == 200
    assert client.post(path, data={"ref": "155-000000", "phone": "+995555123456", "csrf": token}).status_code == 429


def test_rate_limit_stops_guessing_even_the_right_phone(client):
    book(client)
    ref, token = ref_of_only_booking(), csrf(client)
    for _ in range(10):
        client.post("/manage/cancel", data={"ref": ref, "phone": "+995500000000", "csrf": token})
    client.post("/manage/cancel", data={"ref": ref, "phone": "+995555123456", "csrf": token})
    assert sql("SELECT status FROM reservations")[0]["status"] == "pending"


# ---------- admin login ----------
def test_admin_pages_need_login(client):
    for path in ["/admin", "/admin/reservations", "/admin/menu", "/admin/settings", "/admin/chats"]:
        resp = client.get(path)
        assert resp.status_code == 302 and "/admin/login" in resp.headers["Location"], path


def test_wrong_password_is_refused(client):
    login(client, "nope")
    assert client.get("/admin/reservations").status_code == 302


def test_login_locks_out_after_five_failures(client):
    for _ in range(5):
        assert login(client, "nope").status_code == 200
    assert login(client).status_code == 429  # even the right password is refused now
    assert client.get("/admin/reservations").status_code == 302


def test_login_starts_a_fresh_session(client):
    book(client)
    old_token = csrf(client)
    login(client)
    with client.session_transaction() as s:
        assert s.get("admin") is True
        assert "my_refs" not in s and "csrf" not in s  # old session data is gone
    assert csrf(client) != old_token


def test_admin_posts_need_csrf(admin):
    sql("INSERT INTO closures(date,start,end,reason) VALUES(?,?,?,?)", (day(1), "", "", ""))
    assert admin.post("/admin/closures/1/delete").status_code == 400
    assert len(sql("SELECT * FROM closures")) == 1
    assert admin.post("/admin/closures/1/delete", data={"csrf": csrf(admin)}).status_code == 302
    assert sql("SELECT * FROM closures") == []


def test_logout_needs_csrf_and_ends_session(admin):
    assert admin.post("/admin/logout").status_code == 400
    admin.post("/admin/logout", data={"csrf": csrf(admin)})
    assert admin.get("/admin/reservations").status_code == 302


def test_password_change(admin):
    token = csrf(admin)
    admin.post("/admin/password", data={"current": "admin123", "new": "short", "again": "short", "csrf": token})
    assert sql("SELECT * FROM settings WHERE key='admin_hash'") == []
    admin.post("/admin/password", data={"current": "admin123", "new": "a-long-new-pass", "again": "a-long-new-pass", "csrf": token})
    assert sql("SELECT * FROM settings WHERE key='admin_hash'")

    fresh = cafe.app.test_client()
    login(fresh, "admin123")
    assert fresh.get("/admin/reservations").status_code == 302
    login(fresh, "a-long-new-pass")
    assert fresh.get("/admin/reservations").status_code == 200


# ---------- photo uploads ----------
def save_dish(client, photo=None, did=None, **extra):
    data = {"name": "Test dish", "price": "12.50", "category_id": "1", "visible": "1", "csrf": csrf(client), **extra}
    if did:
        data["id"] = str(did)
    if photo:
        data["photo"] = (io.BytesIO(photo[0]), photo[1])
    return client.post("/admin/menu/save", data=data, content_type="multipart/form-data")


def uploaded_files():
    return sorted(p.name for p in cafe.UPLOADS.iterdir())


def last_dish():
    return sql("SELECT * FROM dishes ORDER BY id DESC LIMIT 1")[0]


@pytest.mark.parametrize("content, filename", [
    (b"<?php echo 1; ?>", "evil.png"),   # not really a PNG
    (JPG, "photo.png"),                   # JPEG bytes with a PNG name
    (PNG, "photo.html"),                  # right bytes, wrong extension
])
def test_fake_photos_are_rejected(admin, content, filename):
    count = len(sql("SELECT * FROM dishes"))
    save_dish(admin, photo=(content, filename))
    assert len(sql("SELECT * FROM dishes")) == count
    assert uploaded_files() == []


def test_real_photo_is_stored_under_a_random_name(admin):
    save_dish(admin, photo=(PNG, "../../my photo.png"))
    image = last_dish()["image"]
    assert image.startswith("/media/") and image.endswith(".png")
    assert uploaded_files() == [image.rsplit("/", 1)[1]]
    assert admin.get(image).data == PNG


def test_replacing_or_deleting_a_photo_removes_the_old_file(admin):
    save_dish(admin, photo=(PNG, "a.png"))
    dish = last_dish()
    first = dish["image"]
    save_dish(admin, photo=(JPG, "b.jpg"), did=dish["id"])
    second = last_dish()["image"]
    assert uploaded_files() == [second.rsplit("/", 1)[1]] and first != second

    admin.post(f"/admin/menu/delete/{dish['id']}", data={"csrf": csrf(admin)})
    assert uploaded_files() == []


def test_photo_still_in_use_is_kept(admin):
    save_dish(admin, photo=(PNG, "a.png"))
    dish = last_dish()
    sql("INSERT INTO gallery(image,caption) VALUES(?,?)", (dish["image"], "also in the gallery"))
    admin.post(f"/admin/menu/delete/{dish['id']}", data={"csrf": csrf(admin)})
    assert len(uploaded_files()) == 1


def test_media_route_cannot_escape_uploads_folder(client):
    assert client.get("/media/../app.py").status_code == 404
    assert client.get("/media/..%2Fapp.py").status_code == 404


# ---------- misc hardening ----------
@pytest.mark.parametrize("nxt", ["//evil.example", "https://evil.example", "/\\evil.example", "\\\\evil.example"])
def test_language_switch_does_not_redirect_offsite(client, nxt):
    resp = client.get("/lang/ka", query_string={"next": nxt})
    assert resp.headers["Location"] == "/"


def test_language_switch_keeps_local_page(client):
    assert client.get("/lang/ka?next=/menu").headers["Location"] == "/menu"


def test_security_headers(client):
    h = client.get("/").headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert h["Referrer-Policy"] == "same-origin"


def test_chat_token_only_shows_own_messages(client):
    a = client.post("/api/chat/send", json={"body": "hello from A"}).json["token"]
    b = client.post("/api/chat/send", json={"body": "hello from B"}).json["token"]
    assert [m["body"] for m in client.get(f"/api/chat/messages?token={a}").json] == ["hello from A"]
    assert [m["body"] for m in client.get(f"/api/chat/messages?token={b}").json] == ["hello from B"]
    assert client.get("/api/chat/messages?token=guess").json == []


def test_tab_icon(client):
    assert b'rel="icon"' in client.get("/").data
    resp = client.get("/favicon.ico")
    assert resp.status_code == 301 and resp.headers["Location"] == "/static/favicon.svg"
    assert client.get("/static/favicon.svg").status_code == 200
