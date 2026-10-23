"""Test 7: Negative tests — auth, roles, validation, permissions."""
from datetime import date, timedelta

import httpx
import pytest

from tests.conftest import register_and_login


def _tomorrow() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


class TestNegative:
    """Test 7: All the things that should fail."""

    def test_no_session_returns_401(self, server):
        """No cookie -> 401."""
        client = httpx.Client(base_url=server)
        r = client.get("/auth/me")
        assert r.status_code == 401
        r = client.post("/bookings/", json={
            "resource_id": 1, "date": _tomorrow(),
            "start": "09:00", "end": "10:00",
        })
        assert r.status_code == 401
        client.close()

    def test_role_not_allowed_returns_403(self, server):
        """Lab instructor cannot book research_center or auditorium."""
        client = register_and_login(
            server, "neg_instructor@test.edu", "pass123",
            name="Neg Instructor", role="lab_instructor",
        )
        # Find a research_center resource
        res = client.get("/resources/", params={"type": "research_center", "page_size": 1})
        items = res.json().get("items", [])
        if not items:
            pytest.skip("No research_center resource found")
        rid = items[0]["id"]

        r = client.post("/bookings/", json={
            "resource_id": rid, "date": _tomorrow(),
            "start": "09:00", "end": "10:00",
        })
        assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"
        client.close()

    def test_missing_guide_returns_400(self, server):
        """Student booking a lab without faculty_ref_email -> 400."""
        client = register_and_login(
            server, "neg_student@test.edu", "pass123",
            name="Neg Student", role="student",
        )
        # Find a lab resource
        res = client.get("/resources/", params={"type": "lab", "page_size": 1})
        items = res.json().get("items", [])
        if not items:
            pytest.skip("No lab resource found")
        rid = items[0]["id"]

        r = client.post("/bookings/", json={
            "resource_id": rid, "date": _tomorrow(),
            "start": "09:00", "end": "10:00",
        })
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
        assert "faculty" in r.json()["detail"].lower() or "guide" in r.json()["detail"].lower()
        client.close()

    def test_missing_coordinator_purpose_returns_400(self, server):
        """Student booking a classroom needs coordinator email + purpose >= 10 chars."""
        client = register_and_login(
            server, "neg_student2@test.edu", "pass123",
            name="Neg Student 2", role="student",
        )
        # Find a classroom
        res = client.get("/resources/", params={"type": "classroom", "page_size": 1})
        items = res.json().get("items", [])
        if not items:
            pytest.skip("No classroom found")
        rid = items[0]["id"]

        # No coordinator
        r = client.post("/bookings/", json={
            "resource_id": rid, "date": _tomorrow(),
            "start": "09:00", "end": "10:00",
        })
        assert r.status_code == 400

        # With coordinator but short purpose
        r = client.post("/bookings/", json={
            "resource_id": rid, "date": _tomorrow(),
            "start": "09:00", "end": "10:00",
            "faculty_ref_email": "faculty01@example.edu",
            "purpose": "short",
        })
        assert r.status_code == 400
        assert "purpose" in r.json()["detail"].lower() or "10 char" in r.json()["detail"].lower()
        client.close()

    def test_bad_range_returns_400(self, server):
        """End before start -> 400."""
        client = register_and_login(
            server, "neg_range@test.edu", "pass123",
            name="Neg Range", role="faculty",
        )
        r = client.post("/bookings/", json={
            "resource_id": 1, "date": _tomorrow(),
            "start": "10:00", "end": "09:00",
        })
        assert r.status_code == 400
        client.close()

    def test_outside_hours_returns_400(self, server):
        """Booking outside operating hours -> 400."""
        client = register_and_login(
            server, "neg_hours@test.edu", "pass123",
            name="Neg Hours", role="faculty",
        )
        r = client.post("/bookings/", json={
            "resource_id": 1, "date": _tomorrow(),
            "start": "05:00", "end": "06:00",
        })
        assert r.status_code == 400
        assert "operating hours" in r.json()["detail"].lower()
        client.close()

    def test_off_grid_returns_400(self, server):
        """Times not on 30-minute grid -> 400."""
        client = register_and_login(
            server, "neg_grid@test.edu", "pass123",
            name="Neg Grid", role="faculty",
        )
        r = client.post("/bookings/", json={
            "resource_id": 1, "date": _tomorrow(),
            "start": "09:15", "end": "10:00",
        })
        assert r.status_code == 400
        assert "30-minute" in r.json()["detail"].lower()
        client.close()

    def test_unknown_resource_returns_404(self, server):
        """Non-existent resource -> 404."""
        client = register_and_login(
            server, "neg_404@test.edu", "pass123",
            name="Neg 404", role="faculty",
        )
        r = client.post("/bookings/", json={
            "resource_id": 99999, "date": _tomorrow(),
            "start": "09:00", "end": "10:00",
        })
        assert r.status_code == 404
        client.close()

    def test_cancel_others_booking_returns_403(self, server):
        """User A books, User B tries to cancel -> 403."""
        client_a = register_and_login(
            server, "neg_cancel_a@test.edu", "pass123",
            name="Cancel A", role="faculty",
        )
        r = client_a.post("/bookings/", json={
            "resource_id": 1, "date": _tomorrow(),
            "start": "09:00", "end": "10:00",
        })
        assert r.status_code == 201
        booking_id = r.json()["id"]

        client_b = register_and_login(
            server, "neg_cancel_b@test.edu", "pass123",
            name="Cancel B", role="faculty",
        )
        r2 = client_b.post(f"/bookings/{booking_id}/cancel", json={
            "reason": "I want this slot",
        })
        assert r2.status_code == 403

        client_a.close()
        client_b.close()
