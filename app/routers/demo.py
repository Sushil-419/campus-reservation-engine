"""Conflict Lab — demonstrates the double-booking problem and the DB fix.

Endpoints:
  POST /demo/naive/book     — SELECT-then-INSERT (race-prone)
  POST /demo/protected/book — plain INSERT, EXCLUDE catches overlap → 409
  POST /demo/run             — fires n parallel requests server-side
  GET  /demo/state           — current rows + overlapping pairs
  POST /demo/reset           — truncates both demo tables
"""
import asyncio
import time
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.exc import IntegrityError

from app.db import get_db
from app.config import NAIVE_DELAY_MS

router = APIRouter(prefix="/demo", tags=["conflict-lab"])


class BookRequest(BaseModel):
    room: str = "Room-A"
    start: str = "2026-10-15 10:00"  # naive local time
    end: str = "2026-10-15 11:00"
    who: str = "user"


class RunRequest(BaseModel):
    mode: str  # "naive" or "protected"
    n: int = 20  # number of parallel requests


class RunResult(BaseModel):
    mode: str
    n: int
    results: dict[int, int]  # status_code -> count
    elapsed_ms: int
    naive_delay_ms: int


@router.post("/naive/book", status_code=201)
def book_naive(body: BookRequest, db: DBSession = Depends(get_db)):
    """Naive booking: SELECT to check, then INSERT. Race-prone."""
    ts_range = f"[{body.start},{body.end})"

    # Step 1: Check for overlap (separate SELECT)
    check = db.execute(
        text("""
            SELECT id FROM demo_naive
            WHERE room = :room AND during && :during::tsrange
        """),
        {"room": body.room, "during": ts_range}
    ).fetchone()

    if check:
        raise HTTPException(409, detail="Slot already booked (naive check)")

    # Optional delay to widen the race window (for demo purposes)
    if NAIVE_DELAY_MS > 0:
        time.sleep(NAIVE_DELAY_MS / 1000.0)

    # Step 2: INSERT (gap between SELECT and INSERT = race window)
    db.execute(
        text("""
            INSERT INTO demo_naive (room, during, who)
            VALUES (:room, :during::tsrange, :who)
        """),
        {"room": body.room, "during": ts_range, "who": body.who}
    )
    db.commit()
    return {"status": "booked", "mode": "naive", "who": body.who}


@router.post("/protected/book", status_code=201)
def book_protected(body: BookRequest, db: DBSession = Depends(get_db)):
    """Protected booking: just INSERT. EXCLUDE constraint catches overlap."""
    ts_range = f"[{body.start},{body.end})"
    try:
        db.execute(
            text("""
                INSERT INTO demo_protected (room, during, who)
                VALUES (:room, :during::tsrange, :who)
            """),
            {"room": body.room, "during": ts_range, "who": body.who}
        )
        db.commit()
    except IntegrityError as e:
        db.rollback()
        pgcode = getattr(e.orig, "pgcode", None) if e.orig else None
        if pgcode == "23P01":  # exclusion_violation
            raise HTTPException(409, detail="Slot already booked (constraint)")
        raise
    return {"status": "booked", "mode": "protected", "who": body.who}


@router.post("/run", response_model=RunResult)
async def run_demo(body: RunRequest, request: Request):
    """Fire n parallel HTTP requests at the naive or protected endpoint.
    Done server-side because browsers limit concurrent connections (~6)."""
    if body.mode not in ("naive", "protected"):
        raise HTTPException(400, detail="mode must be 'naive' or 'protected'")
    if body.n < 1 or body.n > 200:
        raise HTTPException(400, detail="n must be between 1 and 200")

    # Build the target URL from the current request's base URL
    base = str(request.base_url).rstrip("/")
    url = f"{base}/demo/{body.mode}/book"

    start_dt = datetime.now()

    async def fire(i: int) -> int:
        async with httpx.AsyncClient() as client:
            payload = {
                "room": "Room-A",
                "start": "2026-10-15 10:00",
                "end": "2026-10-15 11:00",
                "who": f"racer-{i}",
            }
            resp = await client.post(url, json=payload, timeout=30.0)
            return resp.status_code

    # Fire all n requests concurrently
    status_codes = await asyncio.gather(*[fire(i) for i in range(body.n)])

    elapsed = int((datetime.now() - start_dt).total_seconds() * 1000)

    # Count results
    counts: dict[int, int] = {}
    for code in status_codes:
        counts[code] = counts.get(code, 0) + 1

    return RunResult(
        mode=body.mode,
        n=body.n,
        results=counts,
        elapsed_ms=elapsed,
        naive_delay_ms=NAIVE_DELAY_MS,
    )


@router.get("/state")
def get_state(db: DBSession = Depends(get_db)):
    """Return current rows and overlapping pairs in both demo tables."""
    def _rows(table: str) -> list[dict]:
        result = db.execute(text(f"SELECT id, room, during::text, who FROM {table} ORDER BY id"))
        return [{"id": r[0], "room": r[1], "during": r[2], "who": r[3]} for r in result]

    def _overlaps(table: str) -> list[dict]:
        result = db.execute(text(f"""
            SELECT a.id, a.who, b.id, b.who, a.during::text, b.during::text
            FROM {table} a JOIN {table} b
              ON a.room = b.room AND a.during && b.during AND a.id < b.id
            ORDER BY a.id, b.id
        """))
        return [
            {"a_id": r[0], "a_who": r[1], "b_id": r[2], "b_who": r[3],
             "a_during": r[4], "b_during": r[5]}
            for r in result
        ]

    return {
        "naive": {"rows": _rows("demo_naive"), "overlaps": _overlaps("demo_naive")},
        "protected": {"rows": _rows("demo_protected"), "overlaps": _overlaps("demo_protected")},
        "naive_delay_ms": NAIVE_DELAY_MS,
    }


@router.post("/reset")
def reset_demo(db: DBSession = Depends(get_db)):
    """Truncate both demo tables."""
    db.execute(text("TRUNCATE demo_naive, demo_protected RESTART IDENTITY"))
    db.commit()
    return {"status": "reset"}
