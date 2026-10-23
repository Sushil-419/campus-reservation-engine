"""Test fixtures: live-server fixture with 4 workers on a test DB.

The server is started once per session. Each test truncates all tables.
"""
import os
import subprocess
import time
import socket
import sys

import httpx
import pytest

# Test DB
TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:pass@localhost:5433/booking_test"
)

BASE = "http://127.0.0.1:8111"
WORKERS = 1 if sys.platform == "win32" else 4


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(scope="session")
def server():
    """Start uvicorn with 4 workers on test DB, wait for it to be ready."""
    env = os.environ.copy()
    env["DATABASE_URL"] = TEST_DB_URL

    # Run migrations on test DB
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env=env,
        check=True,
    )

    # Seed test data
    subprocess.run(
        [sys.executable, "-m", "scripts.seed_all"],
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env=env,
        check=True,
    )

    # Start server
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1",
            "--port", "8111",
            "--workers", str(WORKERS),
        ],
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env=env,
    )

    # Wait for server to be ready
    for _ in range(30):
        if _port_open(8111):
            break
        time.sleep(0.5)
    else:
        proc.kill()
        raise RuntimeError("Server did not start in time")

    # One more check — hit the health endpoint
    for _ in range(10):
        try:
            r = httpx.get(f"{BASE}/docs", timeout=3)
            if r.status_code < 500:
                break
        except httpx.ConnectError:
            time.sleep(0.5)

    yield BASE

    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(autouse=True)
def clean_tables(server):
    """Truncate booking-related tables before each test (not users/resources/policies)."""
    from sqlalchemy import create_engine, text

    engine = create_engine(TEST_DB_URL)
    with engine.connect() as conn:
        conn.execute(text("TRUNCATE bookings, sessions, audit_log, demo_naive, demo_protected RESTART IDENTITY CASCADE"))
        conn.commit()
    engine.dispose()
    yield


def register_and_login(base: str, email: str, password: str,
                        name: str = "Test User", role: str = "student",
                        department: str | None = None, is_cr: bool = False) -> httpx.Client:
    """Register a user and log in, returning an authenticated httpx.Client."""
    client = httpx.Client(base_url=base, timeout=30.0)
    # Register (ignore if already exists)
    client.post("/auth/register", json={
        "email": email, "name": name, "password": password,
        "role": role, "department": department, "is_cr": is_cr,
    })
    # Login
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return client
