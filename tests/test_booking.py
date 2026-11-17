"""Booking rules: who can book which table, when."""
from conftest import book, csrf, day, login, sql


def reservations():
    return sql("SELECT * FROM reservations ORDER BY id")


# ---------- happy path ----------
def test_booking_is_saved_as_pending_and_redirects_to_confirmation(client, notifications):
    resp = book(client)
    assert resp.status_code == 302
    rows = reservations()
    assert len(rows) == 1
    r = rows[0]
    assert resp.headers["Location"].endswith(f"/reserved/{r['ref']}")
    assert (r["name"], r["phone"], r["date"], r["time"], r["guests"], r["tables"], r["status"]) == \
        ("Nino", "+995555123456", day(1), "12:00", 2, "1", "pending")
    assert r["ref"].startswith("155-")
    assert len(notifications) == 1 and r["ref"] in notifications[0]


def test_auto_confirm_setting_confirms_straight_away(client):
    sql("UPDATE settings SET value='1' WHERE key='auto_confirm'")
    book(client)
    assert reservations()[0]["status"] == "confirmed"


def test_group_can_combine_two_tables(client):
    assert book(client, guests="6", tables=["1", "2"]).status_code == 302
    assert reservations()[0]["tables"] == "1,2"


# ---------- table rules ----------
def test_same_table_same_time_cannot_be_booked_twice(client):
    book(client)
    resp = book(client, phone="+995 555 000 111")
    assert resp.status_code == 409
    assert b"just taken" in resp.data
    assert len(reservations()) == 1


def test_overlapping_time_on_same_table_is_rejected(client):
    book(client, time="12:00")
    assert book(client, time="13:00", phone="+995 555 000 111").status_code == 409  # 90-minute slots overlap


def test_same_table_after_previous_slot_ends_is_allowed(client):
    book(client, time="12:00")
    assert book(client, time="13:30", phone="+995 555 000 111").status_code == 302
    assert len(reservations()) == 2


def test_tables_too_small_for_group(client):
    resp = book(client, guests="5", tables=["1"])
    assert resp.status_code == 409
    assert b"too small" in resp.data


def test_more_tables_than_group_needs(client):
    resp = book(client, guests="2", tables=["1", "2"])
    assert resp.status_code == 409
    assert b"more tables than your group needs" in resp.data


def test_no_table_chosen(client):
    resp = book(client, tables=[])
    assert resp.status_code == 400
    assert b"choose a table" in resp.data


def test_inactive_table_cannot_be_booked(client):
    sql("UPDATE dining_tables SET active=0 WHERE id=1")
    assert book(client).status_code == 409
    assert reservations() == []


def test_cancelled_booking_frees_the_table(client):
    book(client)
    sql("UPDATE reservations SET status='cancelled'")
    assert book(client, phone="+995 555 000 111").status_code == 302


# ---------- per-guest limits ----------
def test_same_phone_cannot_hold_two_overlapping_tables(client):
    book(client, tables=["1"])
    resp = book(client, tables=["2"], time="12:30")
    assert resp.status_code == 409
    assert b"already have a table booked" in resp.data


def test_at_most_three_upcoming_bookings_per_phone(client):
    for offset in (1, 2, 3):
        assert book(client, date=day(offset)).status_code == 302
    resp = book(client, date=day(4))
    assert resp.status_code == 409
    assert b"3 upcoming" in resp.data


def test_group_size_limit(client):
    resp = book(client, guests="13", tables=["1", "2", "3", "4"])
    assert resp.status_code == 400
    assert b"up to 12 guests" in resp.data


# ---------- dates and times ----------
def test_past_date_is_rejected(client):
    assert book(client, date=day(-1)).status_code == 400


def test_date_beyond_booking_window_is_rejected(client):
    assert book(client, date=day(31)).status_code == 400
    assert book(client, date=day(30)).status_code == 302


def test_time_outside_opening_hours_is_rejected(client):
    assert book(client, time="08:00").status_code == 400
    assert book(client, time="21:00").status_code == 400  # 21:00 + 90 min is after 22:00 closing


def test_time_not_on_half_hour_grid_is_rejected(client):
    assert book(client, time="12:15").status_code == 400


def test_closed_weekday_is_rejected(client):
    from datetime import date
    sql("UPDATE hours SET closed=1 WHERE day=?", (date.fromisoformat(day(1)).weekday(),))
    assert book(client).status_code == 400


def test_whole_day_closure_blocks_booking(client):
    sql("INSERT INTO closures(date,start,end,reason) VALUES(?,?,?,?)", (day(1), "", "", "Private party"))
    resp = book(client)
    assert resp.status_code == 400
    assert b"not available" in resp.data


def test_partial_closure_blocks_only_overlapping_slots(client):
    sql("INSERT INTO closures(date,start,end,reason) VALUES(?,?,?,?)", (day(1), "14:00", "16:00", ""))
    assert book(client, time="13:00").status_code == 400  # 13:00-14:30 touches the closure
    assert book(client, time="12:30").status_code == 302  # 12:30-14:00 ends as it starts


# ---------- form validation ----------
def test_form_validation_messages(client):
    assert b"enter your name" in book(client, name="A").data
    assert b"phone number" in book(client, phone="12345").data
    assert b"email address" in book(client, email="not-an-email").data
    assert b"choose a date" in book(client, guests="many").data
    assert reservations() == []


def test_honeypot_field_silently_drops_bots(client):
    resp = book(client, website="http://spam.example")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/")
    assert reservations() == []


# ---------- availability APIs ----------
def test_availability_counts_free_tables(client):
    slot = lambda: next(s for s in client.get(f"/api/availability?date={day(1)}&guests=2").json["slots"]
                        if s["time"] == "12:00")
    assert slot()["tables"] == 5 and slot()["seats"] == 20
    book(client)
    assert slot()["tables"] == 4 and slot()["seats"] == 16


def test_availability_reports_zero_when_group_does_not_fit(client):
    for i, phone in enumerate(["+995 555 000 001", "+995 555 000 002", "+995 555 000 003", "+995 555 000 004"], 1):
        book(client, tables=[str(i)], phone=phone)
    slots = client.get(f"/api/availability?date={day(1)}&guests=5").json["slots"]
    assert next(s for s in slots if s["time"] == "12:00")["tables"] == 0


def test_availability_hides_closed_slots_and_rejects_bad_dates(client):
    sql("INSERT INTO closures(date,start,end,reason) VALUES(?,?,?,?)", (day(1), "", "", ""))
    assert client.get(f"/api/availability?date={day(1)}").json["slots"] == []
    assert client.get(f"/api/availability?date={day(-1)}").status_code == 400
    assert client.get("/api/availability?date=nonsense").status_code == 400


def test_tables_api_hides_booked_tables(client):
    book(client)
    ids = [t["id"] for t in client.get(f"/api/tables?date={day(1)}&time=12:00").json]
    assert ids and 1 not in ids
    assert client.get(f"/api/tables?date={day(1)}&time=12:15").json == []


# ---------- staff bookings ----------
def staff_book(client, guests, time="12:00"):
    return client.post("/admin/reservations/new", data={"name": "Walk-in", "date": day(1), "time": time,
                                                        "guests": str(guests), "csrf": csrf(client)})


def test_staff_booking_uses_smallest_fitting_table_then_combines(client):
    sql("UPDATE dining_tables SET seats=2 WHERE id=1")
    sql("UPDATE dining_tables SET seats=6 WHERE id=5")
    login(client)
    staff_book(client, 2)
    staff_book(client, 9)
    rows = reservations()
    assert rows[0]["tables"] == "1"                                    # 2-seater for 2 guests
    assert rows[1]["tables"] == "5,2" and rows[1]["status"] == "confirmed"  # 6 + 4 seats for 9 guests
    assert rows[1]["source"] == "staff"


def test_staff_booking_fails_when_cafe_is_full(client):
    login(client)
    staff_book(client, 12)
    staff_book(client, 8)
    staff_book(client, 1)
    assert len(reservations()) == 2
