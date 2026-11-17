"""Shared test setup.

app.py creates its database and uploads folder when it is imported, so the
environment variables are set *before* the import. Every test then gets its own
fresh database and uploads folder in pytest's tmp_path.
"""
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

_boot = tempfile.mkdtemp(prefix="155-stairs-tests-")
os.environ["DB_PATH"] = os.path.join(_boot, "boot.db")
os.environ["UPLOAD_DIR"] = os.path.join(_boot, "uploads")
os.environ.pop("PRODUCTION", None)
os.environ.pop("ADMIN_PASSWORD", None)

import app as cafe  # noqa: E402  (must come after the environment is set)

ADMIN_PASSWORD = "admin123"


@pytest.fixture(autouse=True)
def fresh_app(tmp_path, monkeypatch):
    """A brand-new database, uploads folder and rate-limit memory for each test."""
    monkeypatch.setattr(cafe, "DB_PATH", tmp_path / "cafe.db")
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(cafe, "UPLOADS", uploads)
    cafe.LOOKUPS.clear()
    cafe.FAILS.clear()
    sent = []
    monkeypatch.setattr(cafe, "notify", sent.append)  # no Telegram / email from tests
    cafe.app.config["TESTING"] = True
    cafe.init_db()
    yield sent
    cafe.LOOKUPS.clear()
    cafe.FAILS.clear()


@pytest.fixture
def notifications(fresh_app):
    return fresh_app


@pytest.fixture
def client():
    return cafe.app.test_client()


@pytest.fixture
def admin(client):
    login(client)
    return client


def sql(query, params=()):
    """Run SQL straight against the test database and return all rows."""
    con = sqlite3.connect(cafe.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(query, params).fetchall()
        con.commit()
        return rows
    finally:
        con.close()


def day(offset=1):
    """A date string `offset` days from today in the cafe's time zone."""
    return (datetime.now(ZoneInfo("Asia/Tbilisi")).date() + timedelta(days=offset)).isoformat()


def csrf(client):
    """Open a page so the site hands out a CSRF token, then read it from the session."""
    client.get("/reserve")
    with client.session_transaction() as s:
        return s["csrf"]


def book(client, **overrides):
    """Submit the public booking form. Defaults: tomorrow 12:00, 2 guests, table 1."""
    form = {"name": "Nino", "phone": "+995 555 123 456", "email": "", "date": day(1), "time": "12:00",
            "guests": "2", "tables": ["1"], "notes": "", "csrf": csrf(client)}
    form.update(overrides)
    return client.post("/reserve", data=form)


def login(client, password=ADMIN_PASSWORD):
    return client.post("/admin/login", data={"password": password, "csrf": csrf(client)})
