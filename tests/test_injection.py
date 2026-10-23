"""Test 8: SQL injection attempts — nothing breaks, text stored/rejected as data."""
from datetime import date, timedelta

import httpx
import pytest

from tests.conftest import register_and_login


INJECTION_STRINGS = [
    "'; DROP TABLE bookings;--",
    "1; DELETE FROM users WHERE 1=1;--",
    "' OR '1'='1",
    "Robert'); DROP TABLE users;--",
    "1 UNION SELECT * FROM sessions--",
    "<script>alert('xss')</script>",
    "{{7*7}}",
    "${7*7}",
    "' AND 1=CONVERT(int,(SELECT TOP 1 email FROM users))--",
]


def _tomorrow() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


class TestInjection:
    """Test 8: Injection strings in every text field and query parameter."""

    def test_injection_in_register(self, server):
        """Injection strings in registration fields."""
        for i, inj in enumerate(INJECTION_STRINGS):
            client = httpx.Client(base_url=server)
            r = client.post("/auth/register", json={
                "email": f"inj{i}@test.edu",
                "name": inj,
                "password": "pass123",
                "role": "student",
            })
            # Should either succeed (201) or fail with validation (400/422) — never 500
            assert r.status_code < 500, f"Server error with injection string: {inj}"
            client.close()

    def test_injection_in_login(self, server):
        """Injection strings in login email/password."""
        for inj in INJECTION_STRINGS:
            client = httpx.Client(base_url=server)
            r = client.post("/auth/login", json={
                "email": inj + "@test.edu" if "@" not in inj else inj,
                "password": inj,
            })
            assert r.status_code < 500, f"Server error with injection: {inj}"
            client.close()

    def test_injection_in_booking_purpose(self, server):
        """Injection strings in booking purpose field."""
        client = register_and_login(
            server, "inj_purpose@test.edu", "pass123",
            name="Injector", role="faculty",
        )
        for inj in INJECTION_STRINGS:
            r = client.post("/bookings/", json={
                "resource_id": 1,
                "date": _tomorrow(),
                "start": "09:00",
                "end": "10:00",
                "purpose": inj,
            })
            # First one may succeed (201), rest will conflict (409) — never 500
            assert r.status_code < 500, f"Server error with injection purpose: {inj}"
        client.close()

    def test_injection_in_resource_search(self, server):
        """Injection strings in resource search query parameter."""
        client = register_and_login(
            server, "inj_search@test.edu", "pass123",
            name="Search Injector", role="faculty",
        )
        for inj in INJECTION_STRINGS:
            r = client.get("/resources/", params={"q": inj})
            assert r.status_code < 500, f"Server error with search injection: {inj}"
        client.close()

    def test_injection_in_cancel_reason(self, server):
        """Injection strings in cancel reason."""
        client = register_and_login(
            server, "inj_cancel@test.edu", "pass123",
            name="Cancel Injector", role="faculty",
        )
        # Create a booking first
        r = client.post("/bookings/", json={
            "resource_id": 1,
            "date": _tomorrow(),
            "start": "09:00",
            "end": "10:00",
        })
        if r.status_code == 201:
            bid = r.json()["id"]
            for inj in INJECTION_STRINGS:
                r2 = client.post(f"/bookings/{bid}/cancel", json={
                    "reason": inj,
                })
                assert r2.status_code < 500, f"Server error with cancel injection: {inj}"
                # Only first cancel works, rest get 400
        client.close()

    def test_tables_still_exist(self, server):
        """After all injection attempts, all tables still exist and are queryable."""
        from sqlalchemy import create_engine, text
        import os
        db_url = os.getenv(
            "TEST_DATABASE_URL",
            "postgresql+psycopg://postgres:pass@localhost:5433/booking_test"
        )
        engine = create_engine(db_url)
        with engine.connect() as conn:
            for table in ["users", "bookings", "resources", "sessions", "policies",
                          "audit_log", "demo_naive", "demo_protected"]:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                count = result.scalar_one()
                assert count >= 0, f"Table {table} not queryable!"
        engine.dispose()
