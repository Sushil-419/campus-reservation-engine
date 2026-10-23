"""Resources router: list, detail, day view, free slots."""
from datetime import date, datetime, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session as DBSession

from app.db import get_db
from app.models import Resource, Booking
from app.auth import get_current_user, get_optional_user
from app.config import OPERATING_HOURS, DEFAULT_OPERATING_HOURS

router = APIRouter(prefix="/resources", tags=["resources"])


@router.get("/")
def list_resources(
    building: Optional[str] = None,
    floor: Optional[int] = None,
    type: Optional[str] = None,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    db: DBSession = Depends(get_db),
):
    """List resources with optional filters, paginated."""
    query = select(
        Resource.id, Resource.name, Resource.building, Resource.floor,
        Resource.type, Resource.department, Resource.capacity, Resource.is_active,
    ).where(Resource.is_active == True)

    if building:
        query = query.where(Resource.building == building)
    if floor is not None:
        query = query.where(Resource.floor == floor)
    if type:
        query = query.where(Resource.type == type)
    if q:
        query = query.where(Resource.name.ilike(f"%{q}%"))

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = db.execute(count_query).scalar_one()

    # Paginate
    offset = (page - 1) * page_size
    rows = db.execute(
        query.order_by(Resource.building, Resource.floor, Resource.name)
        .offset(offset).limit(page_size)
    ).all()

    return {
        "items": [
            {
                "id": r.id, "name": r.name, "building": r.building,
                "floor": r.floor, "type": r.type, "department": r.department,
                "capacity": r.capacity, "is_active": r.is_active,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/buildings")
def list_buildings(db: DBSession = Depends(get_db)):
    """List distinct buildings for the filter dropdown."""
    rows = db.execute(
        select(Resource.building).where(Resource.is_active == True)
        .distinct().order_by(Resource.building)
    ).scalars().all()
    return rows


@router.get("/{resource_id}")
def get_resource(resource_id: int, db: DBSession = Depends(get_db)):
    """Get resource details by ID."""
    r = db.execute(
        select(Resource).where(Resource.id == resource_id)
    ).scalar_one_or_none()
    if not r:
        raise HTTPException(404, detail="Resource not found")
    return {
        "id": r.id, "name": r.name, "building": r.building,
        "floor": r.floor, "type": r.type, "department": r.department,
        "capacity": r.capacity, "is_active": r.is_active,
    }


@router.get("/{resource_id}/day")
def get_day_view(
    resource_id: int,
    date: str = Query(..., description="YYYY-MM-DD"),
    db: DBSession = Depends(get_db),
):
    """Return bookings for a resource on a given date."""
    resource = db.execute(
        select(Resource).where(Resource.id == resource_id)
    ).scalar_one_or_none()
    if not resource:
        raise HTTPException(404, detail="Resource not found")

    rows = db.execute(
        text("""
            SELECT id, lower(during) AS start, upper(during) AS end,
                   source, status, purpose, user_id
            FROM bookings
            WHERE resource_id = :rid
              AND status = 'confirmed'
              AND during && tsrange(CAST(:day_start AS timestamp), CAST(:day_end AS timestamp))
            ORDER BY lower(during)
        """),
        {
            "rid": resource_id,
            "day_start": f"{date} 00:00",
            "day_end": f"{date} 23:59",
        }
    ).all()

    return [
        {
            "id": r.id,
            "start": r.start.strftime("%H:%M") if r.start else "",
            "end": r.end.strftime("%H:%M") if r.end else "",
            "source": r.source,
            "status": r.status,
            "purpose": (r.purpose[:50] + "...") if r.purpose and len(r.purpose) > 50 else r.purpose,
            "user_id": r.user_id,
        }
        for r in rows
    ]


@router.get("/{resource_id}/free-slots")
def get_free_slots(
    resource_id: int,
    date: str = Query(..., description="YYYY-MM-DD"),
    db: DBSession = Depends(get_db),
):
    """Return free time slots for a resource on a given date.
    Uses a linear sweep over sorted booked intervals — O(n).
    """
    resource = db.execute(
        select(Resource).where(Resource.id == resource_id)
    ).scalar_one_or_none()
    if not resource:
        raise HTTPException(404, detail="Resource not found")

    op_start_h, op_end_h = OPERATING_HOURS.get(resource.type, DEFAULT_OPERATING_HOURS)

    try:
        query_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, detail="Invalid date format, use YYYY-MM-DD")

    day_start = datetime.combine(query_date, time(op_start_h, 0))
    day_end = datetime.combine(query_date, time(op_end_h, 0))

    # Fetch confirmed bookings that overlap this day's operating hours, sorted by start
    rows = db.execute(
        text("""
            SELECT lower(during) AS start, upper(during) AS end
            FROM bookings
            WHERE resource_id = :rid
              AND status = 'confirmed'
              AND during && tsrange(CAST(:day_start AS timestamp), CAST(:day_end AS timestamp))
            ORDER BY lower(during)
        """),
        {
            "rid": resource_id,
            "day_start": day_start.isoformat(),
            "day_end": day_end.isoformat(),
        }
    ).all()

    # Linear sweep to find free windows
    free = []
    cursor = day_start
    for r in rows:
        booking_start = max(r.start, day_start)
        booking_end = min(r.end, day_end)
        if booking_start > cursor:
            free.append({"start": cursor.strftime("%H:%M"), "end": booking_start.strftime("%H:%M")})
        cursor = max(cursor, booking_end)
    if cursor < day_end:
        free.append({"start": cursor.strftime("%H:%M"), "end": day_end.strftime("%H:%M")})

    return free
