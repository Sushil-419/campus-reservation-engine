"""Policy engine: reads rules from the policies table and enforces them.

Check order:
  1. 400 — invalid input (bad dates, missing fields)
  2. 404 — resource not found or inactive
  3. 403 — role not allowed for this resource type
  4. 400 — missing condition field (faculty_ref_email, purpose)
  5. 400 — limit violation (future start, max_advance_days, max_minutes, 30-min grid, same day, operating hours)
  6. 403 — quota exceeded
  7. INSERT → catch 23P01 → 409
"""
from datetime import datetime, date, time
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session as DBSession

from app.models import User, Resource, Policy, Booking
from app.config import OPERATING_HOURS, DEFAULT_OPERATING_HOURS


def _get_applicable_policy(
    db: DBSession, resource_type: str, user: User
) -> Policy:
    """Find the applicable policy row.
    For a CR: check 'cr' row first; if not found or not allowed, fall back to 'student' row.
    For others: look up by role directly.
    Returns the passing policy or raises 403.
    """
    if user.is_cr:
        cr_policy = db.execute(
            select(Policy).where(
                Policy.resource_type == resource_type,
                Policy.actor_kind == "cr",
            )
        ).scalar_one_or_none()

        if cr_policy and cr_policy.allowed:
            return cr_policy

        student_policy = db.execute(
            select(Policy).where(
                Policy.resource_type == resource_type,
                Policy.actor_kind == "student",
            )
        ).scalar_one_or_none()

        if student_policy and student_policy.allowed:
            return student_policy

        raise HTTPException(403, detail="Role not allowed for this resource type")

    policy = db.execute(
        select(Policy).where(
            Policy.resource_type == resource_type,
            Policy.actor_kind == user.role,
        )
    ).scalar_one_or_none()

    if not policy or not policy.allowed:
        raise HTTPException(403, detail="Role not allowed for this resource type")

    return policy


def check_policy(
    db: DBSession,
    user: User,
    resource: Resource,
    booking_date: date,
    start_time: time,
    end_time: time,
    purpose: Optional[str],
    faculty_ref_email: Optional[str],
) -> tuple[Policy, Optional[User]]:
    """Run all policy checks. Returns (applicable_policy, faculty_ref_user_or_None).
    Raises HTTPException on any violation.
    """
    now = datetime.now()
    today = now.date()

    # --- 400: basic input validation ---
    if start_time >= end_time:
        raise HTTPException(400, detail="Start time must be before end time")

    booking_start = datetime.combine(booking_date, start_time)
    booking_end = datetime.combine(booking_date, end_time)

    if booking_start <= now:
        raise HTTPException(400, detail="Booking must start in the future")

    # 30-minute grid check
    if start_time.minute % 30 != 0 or end_time.minute % 30 != 0:
        raise HTTPException(400, detail="Times must be on a 30-minute grid (e.g. 09:00, 09:30)")
    if start_time.second != 0 or end_time.second != 0:
        raise HTTPException(400, detail="Times must be on a 30-minute grid")

    # --- 404: resource exists and is active ---
    if not resource:
        raise HTTPException(404, detail="Resource not found")
    if not resource.is_active:
        raise HTTPException(404, detail="Resource is not active")

    # --- 403: role check ---
    policy = _get_applicable_policy(db, resource.type, user)

    # --- 400: condition check ---
    faculty_ref_user: Optional[User] = None

    if policy.condition == "own_dept":
        if resource.department is not None and resource.department != user.department:
            raise HTTPException(403, detail="Resource is restricted to its own department")

    elif policy.condition == "needs_guide":
        if not faculty_ref_email:
            raise HTTPException(400, detail="Faculty reference email is required for this resource type")
        faculty_ref_user = db.execute(
            select(User).where(
                User.email == faculty_ref_email,
                User.role.in_(["faculty", "hod"]),
            )
        ).scalar_one_or_none()
        if not faculty_ref_user:
            raise HTTPException(400, detail="Faculty reference not found or not a faculty/HOD")

    elif policy.condition == "needs_coordinator":
        if not faculty_ref_email:
            raise HTTPException(400, detail="Faculty/coordinator email is required for this resource type")
        faculty_ref_user = db.execute(
            select(User).where(
                User.email == faculty_ref_email,
                User.role.in_(["faculty", "hod"]),
            )
        ).scalar_one_or_none()
        if not faculty_ref_user:
            raise HTTPException(400, detail="Coordinator not found or not a faculty/HOD")
        if not purpose or len(purpose.strip()) < 10:
            raise HTTPException(400, detail="Purpose must be at least 10 characters for this resource type")

    # --- 400: limit checks ---
    duration_minutes = int((booking_end - booking_start).total_seconds() / 60)
    if duration_minutes > policy.max_minutes:
        raise HTTPException(
            400,
            detail=f"Booking duration ({duration_minutes} min) exceeds maximum ({policy.max_minutes} min)"
        )

    advance_days = (booking_date - today).days
    if advance_days > policy.max_advance_days:
        raise HTTPException(
            400,
            detail=f"Booking is {advance_days} days ahead; maximum is {policy.max_advance_days} days"
        )

    # Operating hours check
    op_start, op_end = OPERATING_HOURS.get(resource.type, DEFAULT_OPERATING_HOURS)
    if start_time < time(op_start, 0) or end_time > time(op_end, 0):
        raise HTTPException(
            400,
            detail=f"Booking must be within operating hours ({op_start:02d}:00 - {op_end:02d}:00)"
        )

    # --- 403: quota check (with user row lock to prevent race) ---
    db.execute(
        select(User).where(User.id == user.id).with_for_update()
    ).scalar_one()

    active_count = db.execute(
        text("""
            SELECT COUNT(*) FROM bookings
            WHERE user_id = :uid
              AND source = 'user'
              AND status = 'confirmed'
              AND upper(during) > now()
        """),
        {"uid": user.id}
    ).scalar_one()

    if active_count >= policy.quota_active:
        raise HTTPException(
            403,
            detail=f"Quota exceeded: you have {active_count} active bookings (max {policy.quota_active})"
        )

    return policy, faculty_ref_user
