"""Concurrency tests: prove the EXCLUDE constraint works under parallel load.

Tests 1-5 from the spec:
1. 20 parallel same-slot -> exactly 1 success
2. Partial overlaps -> exactly 1 success
3. 20 different rooms -> all succeed
4. Adjacent bookings both succeed
5. Quota race: 1 user, 5 parallel non-overlapping slots, quota 2 -> exactly 2 success
"""
import threading
from datetime import date, timedelta

import httpx
import pytest

from tests.conftest import register_and_login, BASE


def _tomorrow() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


def _future_date(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


class TestConcurrency:
    """Test 1: 20 parallel bookings for the same slot — exactly 1 wins."""

    def test_20_parallel_same_slot(self, server):
        """20 users book the exact same slot simultaneously.
        Exactly 1 should get 201, 19 should get 409."""
        NUM = 20
        barrier = threading.Barrier(NUM)
        results = []
        lock = threading.Lock()
        tomorrow = _tomorrow()

        def attempt(i):
            client = register_and_login(
                server, f"race{i}@test.edu", "pass123",
                name=f"Racer {i}", role="faculty",
            )
            barrier.wait()
            r = client.post("/bookings/", json={
                "resource_id": 1,
                "date": tomorrow,
                "start": "09:00",
                "end": "10:00",
            })
            with lock:
                results.append(r.status_code)
            client.close()

        threads = [threading.Thread(target=attempt, args=(i,)) for i in range(NUM)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        successes = results.count(201)
        conflicts = results.count(409)
        print(f"\nTest 1 results: {successes} success, {conflicts} conflicts")
        print(f"All codes: {sorted(results)}")

        assert successes == 1, f"Expected 1 success, got {successes}"
        assert conflicts == NUM - 1, f"Expected {NUM-1} conflicts, got {conflicts}"

    def test_partial_overlaps(self, server):
        """Test 2: Three overlapping ranges — only one should succeed."""
        barrier = threading.Barrier(3)
        results = []
        lock = threading.Lock()
        tomorrow = _tomorrow()

        slots = [
            ("09:00", "10:00"),
            ("09:30", "10:30"),
            ("09:00", "12:00"),
        ]

        def attempt(i):
            client = register_and_login(
                server, f"overlap{i}@test.edu", "pass123",
                name=f"Overlapper {i}", role="faculty",
            )
            barrier.wait()
            r = client.post("/bookings/", json={
                "resource_id": 1,
                "date": tomorrow,
                "start": slots[i][0],
                "end": slots[i][1],
            })
            with lock:
                results.append(r.status_code)
            client.close()

        threads = [threading.Thread(target=attempt, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        successes = results.count(201)
        print(f"\nTest 2 results: {successes} success, codes={results}")
        assert successes == 1, f"Expected 1 success, got {successes}"

    def test_20_different_rooms(self, server):
        """Test 3: 20 users book 20 different resources — all should succeed."""
        NUM = 20
        barrier = threading.Barrier(NUM)
        results = []
        lock = threading.Lock()
        tomorrow = _tomorrow()

        def attempt(i):
            client = register_and_login(
                server, f"room{i}@test.edu", "pass123",
                name=f"Room User {i}", role="faculty",
            )
            barrier.wait()
            r = client.post("/bookings/", json={
                "resource_id": i + 1,  # Different resource for each
                "date": tomorrow,
                "start": "09:00",
                "end": "10:00",
            })
            with lock:
                results.append(r.status_code)
            client.close()

        threads = [threading.Thread(target=attempt, args=(i,)) for i in range(NUM)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        successes = results.count(201)
        print(f"\nTest 3 results: {successes} success out of {NUM}")
        assert successes == NUM, f"Expected all {NUM} to succeed, got {successes}"

    def test_adjacent_bookings(self, server):
        """Test 4: Adjacent bookings (9-10 then 10-11) both succeed because [) ranges."""
        client = register_and_login(
            server, "adjacent@test.edu", "pass123",
            name="Adjacent User", role="faculty",
        )
        tomorrow = _tomorrow()

        r1 = client.post("/bookings/", json={
            "resource_id": 1, "date": tomorrow,
            "start": "09:00", "end": "10:00",
        })
        r2 = client.post("/bookings/", json={
            "resource_id": 1, "date": tomorrow,
            "start": "10:00", "end": "11:00",
        })

        print(f"\nTest 4: slot 1 = {r1.status_code}, slot 2 = {r2.status_code}")
        assert r1.status_code == 201, f"First slot failed: {r1.text}"
        assert r2.status_code == 201, f"Adjacent slot failed: {r2.text}"
        client.close()

    def test_quota_race(self, server):
        """Test 5: One user, 5 parallel non-overlapping slots, quota=2 -> exactly 2 succeed."""
        # Use a student with quota=2
        client = register_and_login(
            server, "quotaracer@test.edu", "pass123",
            name="Quota Racer", role="student",
        )
        cookies = dict(client.cookies)
        client.close()

        NUM = 5
        barrier = threading.Barrier(NUM)
        results = []
        lock = threading.Lock()

        def attempt(i):
            c = httpx.Client(base_url=server, cookies=cookies)
            d = _future_date(i + 1)
            r = c.post("/bookings/", json={
                "resource_id": 1,  # sports (direct for students)
                "date": d,
                "start": "09:00",
                "end": "10:00",
            })
            with lock:
                results.append(r.status_code)
            c.close()

        # Need to find a sports resource ID first
        probe = httpx.Client(base_url=server, cookies=cookies)
        res = probe.get("/resources/", params={"type": "sports", "page_size": 1})
        probe.close()

        if res.status_code == 200 and res.json().get("items"):
            sports_id = res.json()["items"][0]["id"]
        else:
            pytest.skip("No sports resource found for quota test")
            return

        def attempt_sports(i):
            c = httpx.Client(base_url=server, cookies=cookies)
            d = _future_date(i + 1)
            barrier.wait()
            r = c.post("/bookings/", json={
                "resource_id": sports_id,
                "date": d,
                "start": "09:00",
                "end": "10:00",
            })
            with lock:
                results.append(r.status_code)
            c.close()

        threads = [threading.Thread(target=attempt_sports, args=(i,)) for i in range(NUM)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        successes = results.count(201)
        quota_hit = results.count(403)
        print(f"\nTest 5 results: {successes} success, {quota_hit} quota exceeded, all={results}")
        assert successes == 2, f"Expected 2 successes (quota=2), got {successes}"
