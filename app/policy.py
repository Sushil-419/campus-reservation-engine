"""Policy engine: reads rules from the policies table and enforces them.

Check order:
  1. 400 — invalid input (bad dates, missing fields)
  2. 404 — resource not found or inactive
  3. 403 — role not allowed for this resource type
  4. 403 — CR: resource not in own branch/dept
  5. 403 — club_president: club not active
  6. 403 — faculty/lab_instructor cross-dept: auto-redirect to request flow
  7. 400 — missing condition field (faculty_ref_email, purpose)
  8. 400 — limit violation (future start, max_advance_days, max_minutes, 30-min grid, operating hours)
  9. 403 — quota exceeded
 10. INSERT → catch 23P01 → 409
"""
from datetime import datetime, date, time
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session as DBSession

from app.models import (
    User, Resource, Policy, Booking, HodBuilding,
    DIRECT_BOOK_ROLES, CAMPUS_RESOURCE_TYPES, CR_REQUESTABLE_TYPES,
)
from app.config import OPERATING_HOURS, DEFAULT_OPERATING_HOURS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_role(user: User, *roles: str) -> None:
    """Raise 403 if user's role is not in the allowed set."""
    if user.role not in roles:
        raise HTTPException(403, detail=f"Role '{user.role}' not permitted for this action")


def get_hod_for_resource(db: DBSession, resource: Resource) -> Optional[User]:
    """Return the HOD who manages this resource's building+department, or None."""
    if not resource.department:
        return None
    row = db.execute(
        select(User).join(
            HodBuilding, HodBuilding.hod_id == User.id
        ).where(
            HodBuilding.building == resource.building,
            HodBuilding.department == resource.department,
            User.role == "hod",
        )
    ).scalar_one_or_none()
    return row


def get_all_hods_for_resource(db: DBSession, resource: Resource):
    """Return ALL HODs who manage this resource's building+department."""
    if not resource.department:
        return []
    rows = db.execute(
        select(User).join(
            HodBuilding, HodBuilding.hod_id == User.id
        ).where(
            HodBuilding.building == resource.building,
            HodBuilding.department == resource.department,
            User.role == "hod",
        )
    ).scalars().all()
    return rows


def hod_manages_resource(db: DBSession, hod: User, resource: Resource) -> bool:
    """Return True if the HOD is assigned to this resource's building+department."""
    if hod.role not in ("hod", "super_admin", "admin"):
        return False
    if hod.role in ("super_admin", "admin"):
        return True
    if not resource.department:
        # Campus-wide resources (Auditorium, Playground, Courts) are NOT under any HOD
        return False
    if hod.department and resource.department == hod.department:
        return True
    row = db.execute(
        select(HodBuilding).where(
            HodBuilding.hod_id == hod.id,
            HodBuilding.building == resource.building,
            HodBuilding.department == resource.department,
        )
    ).scalar_one_or_none()
    return row is not None


# ---------------------------------------------------------------------------
# Request-flow eligibility check (does this booking need approval?)
# ---------------------------------------------------------------------------

def needs_request_flow(user: User, resource: Resource) -> bool:
    """Return True if this user+resource combo must go through the request flow
    instead of direct booking.
    """
    role = user.role

    # CR: always request flow
    if role == "cr":
        return True

    # Club president: always request flow
    if role == "club_president":
        return True

    # Faculty / lab_instructor booking cross-department resource
    if role in ("faculty", "lab_instructor"):
        if resource.department and resource.department != user.department:
            return True

    # Campus resources: only super_admin can book directly; everyone else requests
    if resource.type in CAMPUS_RESOURCE_TYPES:
        if role not in ("super_admin",):
            return True

    return False


# ---------------------------------------------------------------------------
# Pre-booking role guard (called before the full policy check)
# ---------------------------------------------------------------------------

def check_role_allowed(user: User, resource: Resource) -> None:
    """Hard role guards — raise 403 immediately for clearly forbidden combinations."""
    role = user.role

    # CR can only request classrooms/labs
    if role == "cr":
        if resource.type not in CR_REQUESTABLE_TYPES:
            raise HTTPException(
                403,
                detail=f"CR can only request classrooms or labs, not '{resource.type}'"
            )
        # CR can only request within their own branch's department
        if resource.department and user.branch and resource.department != user.branch:
            raise HTTPException(
                403,
                detail="CR can only request resources within their own branch department"
            )

    # HOD cannot directly book campus-wide resources (auditorium, sports, club_room)
    if role == "hod" and resource.type in CAMPUS_RESOURCE_TYPES:
        raise HTTPException(
            403,
            detail=f"HODs cannot book campus resources ('{resource.type}'). "
                   f"Contact super_admin."
        )

    # admin cannot book campus-wide resources directly (they manage, not book)
    if role == "admin" and resource.type in CAMPUS_RESOURCE_TYPES:
        raise HTTPException(
            403,
            detail=f"Admins cannot book campus resources directly. Use super_admin."
        )

    # Club president must have an active club
    if role == "club_president":
        if not user.club_id:
            raise HTTPException(403, detail="No club associated with this account")
        # club.is_active is checked in the router (we pass the loaded user)


# ---------------------------------------------------------------------------
# Original policy lookup (direct-booking path only)
# ---------------------------------------------------------------------------

def _get_applicable_policy(db: DBSession, resource_type: str, user: User) -> Policy:
    """Find the applicable policy row for direct bookings.
    Raises 403 if role is not allowed for this resource type.
    """
    policy = db.execute(
        select(Policy).where(
            Policy.resource_type == resource_type,
            Policy.actor_kind == user.role,
        )
    ).scalar_one_or_none()

    if not policy or not policy.allowed:
        raise HTTPException(403, detail=f"Role '{user.role}' not allowed for resource type '{resource_type}'")

    return policy


# ---------------------------------------------------------------------------
# Main policy check (direct-booking path)
# ---------------------------------------------------------------------------

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
    """Run all policy checks for a DIRECT booking.
    Returns (applicable_policy, faculty_ref_user_or_None).
    Raises HTTPException on any violation.
    """
    now = datetime.now()
    today = now.date()

    # --- 400: basic input validation ---
    if start_time >= end_time:
        raise HTTPException(400, detail="Start time must be before end time")

    booking_start = datetime.combine(booking_date, start_time)
    booking_end   = datetime.combine(booking_date, end_time)

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

    # --- Role guards ---
    check_role_allowed(user, resource)

    # --- 403: If this should be a request, refuse direct booking ---
    if needs_request_flow(user, resource):
        raise HTTPException(
            403,
            detail="Your role requires a booking request for this resource. "
                   "Use POST /requests/ instead."
        )

    # --- 403: HOD must manage this resource's building ---
    if user.role == "hod":
        if not hod_manages_resource(db, user, resource):
            raise HTTPException(
                403,
                detail="You are not assigned to manage this building/department"
            )

    # --- 403: role check via policy table ---
    policy = _get_applicable_policy(db, resource.type, user)

    # --- 400: condition checks ---
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


# ---------------------------------------------------------------------------
# Request-flow policy check (for CR, club_president, cross-dept faculty)
# ---------------------------------------------------------------------------

def check_request_policy(
    db: DBSession,
    user: User,
    resource: Resource,
    booking_date: date,
    start_time: time,
    end_time: time,
    purpose: str,
) -> None:
    """Validate a booking request (not a direct booking).
    Raises HTTPException on violations.
    """
    now = datetime.now()
    today = now.date()

    # Basic time validation
    if start_time >= end_time:
        raise HTTPException(400, detail="Start time must be before end time")
    if datetime.combine(booking_date, start_time) <= now:
        raise HTTPException(400, detail="Request must start in the future")
    if start_time.minute % 30 != 0 or end_time.minute % 30 != 0:
        raise HTTPException(400, detail="Times must be on a 30-minute grid")
    if not resource or not resource.is_active:
        raise HTTPException(404, detail="Resource not found or inactive")

    # Purpose is mandatory for all requests
    if not purpose or len(purpose.strip()) < 10:
        raise HTTPException(400, detail="Purpose must be at least 10 characters")

    # Role-specific guards
    check_role_allowed(user, resource)

    # Club president: club must be active
    if user.role == "club_president":
        if not user.club_id:
            raise HTTPException(403, detail="No club associated with this account")
        from app.models import Club
        club = db.execute(select(Club).where(Club.id == user.club_id)).scalar_one_or_none()
        if not club or not club.is_active:
            raise HTTPException(403, detail="Your club is not yet approved by admin")

    # Operating hours
    op_start, op_end = OPERATING_HOURS.get(resource.type, DEFAULT_OPERATING_HOURS)
    if start_time < time(op_start, 0) or end_time > time(op_end, 0):
        raise HTTPException(
            400,
            detail=f"Request must be within operating hours ({op_start:02d}:00 - {op_end:02d}:00)"
        )

    # Max advance days (use a generous default for requests: 60 days)
    advance_days = (booking_date - today).days
    if advance_days > 60:
        raise HTTPException(400, detail="Cannot request more than 60 days in advance")

    # Duration
    duration_minutes = int(
        (datetime.combine(booking_date, end_time) -
         datetime.combine(booking_date, start_time)).total_seconds() / 60
    )
    if duration_minutes > 480:  # 8 hours max for requests
        raise HTTPException(400, detail="Request duration cannot exceed 8 hours")
