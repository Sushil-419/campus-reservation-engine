"""Bookings router: create, cancel, list, history."""
from datetime import datetime, date, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.db import get_db
from app.models import User, Resource, Booking, AuditLog
from app.auth import get_current_user
from app.policy import check_policy
from app.audit import write_audit

router = APIRouter(prefix="/bookings", tags=["bookings"])


# --- Schemas ---

class BookingCreate(BaseModel):
    resource_id: int
    date: str          # YYYY-MM-DD
    start: str         # HH:MM
    end: str           # HH:MM
    purpose: str | None = None
    faculty_ref_email: str | None = None


class BookingOut(BaseModel):
    id: int
    resource_id: int
    user_id: int
    start: str
    end: str
    date: str
    source: str
    status: str
    purpose: str | None
    faculty_ref_id: int | None
    course: str | None
    created_at: str
    cancelled_at: str | None
    cancel_reason: str | None
    resource_name: str | None = None
    resource_building: str | None = None

    model_config = {"from_attributes": True}


class CancelRequest(BaseModel):
    reason: str


class BookingHistoryEntry(BaseModel):
    at: str
    action: str
    outcome: str
    actor_id: int | None
    detail: dict | None


def _booking_to_out(b: Booking, resource: Resource | None = None) -> dict:
    """Convert a Booking ORM object to BookingOut dict."""
    # Extract start/end from the tsrange 'during' column
    # during is a psycopg Range object
    during = b.during
    start_dt = during.lower if during else None
    end_dt = during.upper if during else None
    return {
        "id": b.id,
        "resource_id": b.resource_id,
        "user_id": b.user_id,
        "start": start_dt.strftime("%H:%M") if start_dt else "",
        "end": end_dt.strftime("%H:%M") if end_dt else "",
        "date": start_dt.strftime("%Y-%m-%d") if start_dt else "",
        "source": b.source,
        "status": b.status,
        "purpose": b.purpose,
        "faculty_ref_id": b.faculty_ref_id,
        "course": b.course,
        "created_at": b.created_at.isoformat() if b.created_at else "",
        "cancelled_at": b.cancelled_at.isoformat() if b.cancelled_at else None,
        "cancel_reason": b.cancel_reason,
        "resource_name": resource.name if resource else None,
        "resource_building": resource.building if resource else None,
    }


@router.post("/", status_code=201)
def create_booking(
    body: BookingCreate,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Create a booking after policy checks. The EXCLUDE constraint is the final guard."""
    # Parse date and times
    try:
        booking_date = date.fromisoformat(body.date)
        start_time = time.fromisoformat(body.start)
        end_time = time.fromisoformat(body.end)
    except ValueError:
        raise HTTPException(400, detail="Invalid date or time format (use YYYY-MM-DD and HH:MM)")

    # Load resource
    resource = db.execute(
        select(Resource).where(Resource.id == body.resource_id)
    ).scalar_one_or_none()

    # Policy checks (raises on violation)
    policy, faculty_ref_user = check_policy(
        db, user, resource, booking_date, start_time, end_time,
        body.purpose, body.faculty_ref_email,
    )

    # Build the tsrange string for Postgres
    start_dt = datetime.combine(booking_date, start_time)
    end_dt = datetime.combine(booking_date, end_time)
    ts_range = f"[{start_dt},{end_dt})"

    # INSERT — the EXCLUDE constraint is the real guard
    try:
        result = db.execute(
            text("""
                INSERT INTO bookings (resource_id, user_id, during, source, status, purpose, faculty_ref_id)
                VALUES (:resource_id, :user_id, CAST(:during AS tsrange), 'user', 'confirmed', :purpose, :faculty_ref_id)
                RETURNING id
            """),
            {
                "resource_id": body.resource_id,
                "user_id": user.id,
                "during": ts_range,
                "purpose": body.purpose,
                "faculty_ref_id": faculty_ref_user.id if faculty_ref_user else None,
            }
        )
        booking_id = result.scalar_one()
        db.commit()
    except IntegrityError as e:
        db.rollback()
        pgcode = (getattr(e.orig, "sqlstate", None) or getattr(e.orig, "pgcode", None)) if e.orig else None
        if pgcode == "23P01":  # exclusion_violation
            write_audit(
                action="book", entity="booking", outcome="conflict",
                actor_id=user.id,
                detail={"resource_id": body.resource_id, "date": body.date,
                        "start": body.start, "end": body.end},
            )
            raise HTTPException(409, detail="Slot already booked")
        raise

    write_audit(
        action="book", entity="booking", outcome="success",
        actor_id=user.id, entity_id=booking_id,
        detail={"resource_id": body.resource_id, "date": body.date,
                "start": body.start, "end": body.end},
        db=db,
    )
    return {"id": booking_id, "status": "confirmed"}


@router.get("/mine")
def list_my_bookings(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List the current user's bookings, paginated."""
    offset = (page - 1) * page_size
    bookings = db.execute(
        select(Booking, Resource).join(Resource, Booking.resource_id == Resource.id).where(
            Booking.user_id == user.id
        ).order_by(Booking.created_at.desc()).offset(offset).limit(page_size)
    ).all()

    total = db.execute(
        select(func.count(Booking.id)).where(Booking.user_id == user.id)
    ).scalar_one()

    return {
        "items": [_booking_to_out(b, r) for b, r in bookings],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/named-me")
def list_bookings_naming_me(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List bookings that name the current user as faculty reference."""
    offset = (page - 1) * page_size
    bookings = db.execute(
        select(Booking, Resource).join(Resource, Booking.resource_id == Resource.id).where(
            Booking.faculty_ref_id == user.id
        ).order_by(Booking.created_at.desc()).offset(offset).limit(page_size)
    ).all()

    total = db.execute(
        select(func.count(Booking.id)).where(Booking.faculty_ref_id == user.id)
    ).scalar_one()

    return {
        "items": [_booking_to_out(b, r) for b, r in bookings],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/{booking_id}/cancel")
def cancel_booking(
    booking_id: int,
    body: CancelRequest,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Cancel a booking. Allowed for: creator, named faculty, HOD of resource department."""
    booking = db.execute(
        select(Booking).where(Booking.id == booking_id)
    ).scalar_one_or_none()
    if not booking:
        raise HTTPException(404, detail="Booking not found")

    if booking.status == "cancelled":
        raise HTTPException(400, detail="Already cancelled")

    if not body.reason or not body.reason.strip():
        raise HTTPException(400, detail="Cancel reason is required")

    # Check permission
    resource = db.execute(
        select(Resource).where(Resource.id == booking.resource_id)
    ).scalar_one_or_none()

    allowed = False
    # Creator can cancel
    if booking.user_id == user.id:
        allowed = True
    # Named faculty can cancel
    if booking.faculty_ref_id == user.id:
        allowed = True
    # HOD of resource's department can cancel
    if user.role == "hod" and resource and resource.department == user.department:
        allowed = True
    # For timetable bookings, the teaching faculty (creator) can cancel
    if booking.source == "timetable" and booking.user_id == user.id:
        allowed = True

    if not allowed:
        raise HTTPException(403, detail="Not authorized to cancel this booking")

    booking.status = "cancelled"
    booking.cancelled_at = datetime.now()
    booking.cancelled_by = user.id
    booking.cancel_reason = body.reason.strip()
    db.commit()

    write_audit(
        action="cancel", entity="booking", outcome="success",
        actor_id=user.id, entity_id=booking_id,
        detail={"reason": body.reason.strip()},
    )
    return {"id": booking_id, "status": "cancelled"}


@router.get("/{booking_id}/history")
def booking_history(
    booking_id: int,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """View audit history for a booking. Allowed for creator, named faculty, HOD."""
    booking = db.execute(
        select(Booking).where(Booking.id == booking_id)
    ).scalar_one_or_none()
    if not booking:
        raise HTTPException(404, detail="Booking not found")

    resource = db.execute(
        select(Resource).where(Resource.id == booking.resource_id)
    ).scalar_one_or_none()

    # Permission check
    allowed = (
        booking.user_id == user.id
        or booking.faculty_ref_id == user.id
        or (user.role == "hod" and resource and resource.department == user.department)
    )
    if not allowed:
        raise HTTPException(403, detail="Not authorized to view this booking's history")

    entries = db.execute(
        select(
            AuditLog.at, AuditLog.action, AuditLog.outcome,
            AuditLog.actor_id, AuditLog.detail
        ).where(
            AuditLog.entity == "booking",
            AuditLog.entity_id == booking_id,
        ).order_by(AuditLog.at)
    ).all()

    return [
        {
            "at": e.at.isoformat() if e.at else "",
            "action": e.action,
            "outcome": e.outcome,
            "actor_id": e.actor_id,
            "detail": e.detail,
        }
        for e in entries
    ]
