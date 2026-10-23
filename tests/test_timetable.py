"""Test 6: Timetable slot blocking and rebooking after cancel."""
from datetime import date, timedelta

import httpx
import pytest

from tests.conftest import register_and_login


class TestTimetable:
    """Test 6: Booking over a timetable slot -> 409; cancel then rebook -> 201."""

    def test_timetable_block_and_rebook(self, server):
        """Insert a timetable booking, try to book over it (409),
        cancel the timetable booking, rebook (201)."""
        from sqlalchemy import create_engine, text
        import os

        db_url = os.getenv(
            "TEST_DATABASE_URL",
            "postgresql+psycopg://postgres:pass@localhost:5433/booking_test"
        )
        engine = create_engine(db_url)

        tomorrow = (date.today() + timedelta(days=1)).isoformat()

        # Insert a timetable booking directly into DB
        with engine.connect() as conn:
            # Find resource 1 and faculty user
            faculty = conn.execute(text(
                "SELECT id FROM users WHERE role = 'faculty' LIMIT 1"
            )).scalar_one()

            conn.execute(text("""
                INSERT INTO bookings (resource_id, user_id, during, source, status, course)
                VALUES (
                    1, :fid,
                    tsrange(CAST(:start AS timestamp), CAST(:end AS timestamp), '[)'),
                    'timetable', 'confirmed', 'CS101'
                )
            """), {
                "fid": faculty,
                "start": f"{tomorrow} 09:00",
                "end": f"{tomorrow} 10:00",
            })
            conn.commit()
        engine.dispose()

        # Try to book over it — should get 409
        client = register_and_login(
            server, "timetable_test@test.edu", "pass123",
            name="Timetable Tester", role="faculty",
        )

        r = client.post("/bookings/", json={
            "resource_id": 1,
            "date": tomorrow,
            "start": "09:00",
            "end": "10:00",
        })
        assert r.status_code == 409, f"Expected 409 over timetable slot, got {r.status_code}: {r.text}"

        # Cancel the timetable booking (faculty who created it can cancel)
        # First find the booking id
        engine2 = create_engine(db_url)
        with engine2.connect() as conn:
            bid = conn.execute(text(
                "SELECT id FROM bookings WHERE source = 'timetable' AND status = 'confirmed' LIMIT 1"
            )).scalar_one()
        engine2.dispose()

        # Login as the faculty who owns it
        faculty_client = register_and_login(
            server, "faculty01@example.edu", "faculty123",
            name="Faculty 01", role="faculty",
        )
        cancel_resp = faculty_client.post(f"/bookings/{bid}/cancel", json={
            "reason": "Class cancelled for the day"
        })
        assert cancel_resp.status_code == 200, f"Cancel failed: {cancel_resp.text}"

        # Now rebook — should succeed
        r2 = client.post("/bookings/", json={
            "resource_id": 1,
            "date": tomorrow,
            "start": "09:00",
            "end": "10:00",
        })
        assert r2.status_code == 201, f"Expected 201 after cancellation, got {r2.status_code}: {r2.text}"

        client.close()
        faculty_client.close()
