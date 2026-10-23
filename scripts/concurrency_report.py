"""Concurrency report: runs test 1 and prints results as a table for the demo.

Run: python -m scripts.concurrency_report
Requires the server to be running on localhost:8000 with 4 workers.
"""
import threading
from datetime import date, timedelta

import httpx

BASE = "http://127.0.0.1:8000"
NUM = 20


def register_and_login(i: int) -> httpx.Client:
    client = httpx.Client(base_url=BASE, timeout=30.0)
    email = f"report_racer{i}@test.edu"
    client.post("/auth/register", json={
        "email": email, "name": f"Racer {i}",
        "password": "pass123", "role": "faculty",
    })
    resp = client.post("/auth/login", json={
        "email": email, "password": "pass123",
    })
    if resp.status_code != 200:
        print(f"  Login failed for racer {i}: {resp.status_code}")
    return client


def main():
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    print("=" * 70)
    print("CONCURRENCY REPORT — 20 Parallel Booking Requests")
    print("=" * 70)
    print(f"Target: Resource ID 1, Date: {tomorrow}, Slot: 09:00–10:00")
    print(f"Workers: 4 (uvicorn), Threads: {NUM}")
    print()

    # Register and login all users first
    print("Preparing users...")
    clients = [register_and_login(i) for i in range(NUM)]

    barrier = threading.Barrier(NUM)
    results = []
    lock = threading.Lock()

    def attempt(i):
        barrier.wait()
        r = clients[i].post("/bookings/", json={
            "resource_id": 1,
            "date": tomorrow,
            "start": "09:00",
            "end": "10:00",
        })
        with lock:
            results.append((i, r.status_code, r.json()))

    print(f"Firing {NUM} simultaneous requests...\n")

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(NUM)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    # Sort by user index
    results.sort(key=lambda x: x[0])

    # Print table
    print(f"{'User':>8}  {'Status':>8}  {'Result'}")
    print("-" * 50)
    for idx, status, body in results:
        icon = "[OK]      " if status == 201 else "[CONFLICT]"
        detail = body.get("status", body.get("detail", ""))
        print(f"  {idx:>4}     {status:>5}    {icon} {detail}")

    print("-" * 50)
    successes = sum(1 for _, s, _ in results if s == 201)
    conflicts = sum(1 for _, s, _ in results if s == 409)
    others = sum(1 for _, s, _ in results if s not in (201, 409))

    print(f"\n{'SUMMARY':}")
    print(f"  Successes (201): {successes}")
    print(f"  Conflicts (409): {conflicts}")
    print(f"  Other:           {others}")
    print(f"\n  DB rows created: {successes}")
    print(f"  Expected:        1 success, {NUM - 1} conflicts")
    print(f"  Result:          {'PASS' if successes == 1 else 'FAIL'}")
    print("=" * 70)

    for c in clients:
        c.close()


if __name__ == "__main__":
    main()
