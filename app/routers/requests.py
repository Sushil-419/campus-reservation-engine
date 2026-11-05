"""Booking Requests router.

Who raises requests:
  - cr           → classrooms / labs in own branch dept → goes to that dept's HOD
  - club_president → any resource → dept resource goes to HOD; campus resource to super_admin/admin
  - faculty / lab_instructor → cross-dept resource → goes to that dept's HOD

Who approves:
  - hod          → requests for resources in their assigned buildings/depts
  - super_admin  → requests for campus-wide resources (auditorium, sports, club_room)
  - admin        → can approve any request (delegated authority)
"""
from datetime import datetime, date, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.db import get_db
from app.models import (
    User, Resource, BookingRequest, Booking, HodBuilding,
    CAMPUS_RESOURCE_TYPES,
)
from app.auth import get_current_user
from app.policy import check_request_policy, hod_manages_resource
from app.audit import write_audit

router = APIRouter(prefix="/requests", tags=["booking-requests"])

# Roles that can raise requests
REQUESTER_ROLES = {"cr", "club_president", "faculty", "lab_instructor"}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RequestCreate(BaseModel):
    resource_id: int
    date: str         # YYYY-MM-DD
    start: str        # HH:MM
    end: str          # HH:MM
    purpose: str


class RequestOut(BaseModel):
    id: int
    resource_id: int
    requester_id: int
    start: str
    end: str
    date: str
    purpose: str
    status: str
    reviewed_by: int | None
    review_note: str | None
    reviewed_at: str | None
    booking_id: int | None
    created_at: str
    resource_name: str | None = None
    resource_type: str | None = None
    resource_building: str | None = None

    model_config = {"from_attributes": True}


class ReviewRequest(BaseModel):
    approve: bool
    note: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _request_to_out(req: BookingRequest, resource: Optional[Resource] = None) -> dict:
    during = req.during
    start_dt = during.lower if during else None
    end_dt   = during.upper if during else None
    return {
        "id": req.id,
        "resource_id": req.resource_id,
        "requester_id": req.requester_id,
        "start": start_dt.strftime("%H:%M") if start_dt else "",
        "end":   end_dt.strftime("%H:%M")   if end_dt   else "",
        "date":  start_dt.strftime("%Y-%m-%d") if start_dt else "",
        "purpose": req.purpose,
        "status": req.status,
        "reviewed_by": req.reviewed_by,
        "review_note": req.review_note,
        "reviewed_at": req.reviewed_at.isoformat() if req.reviewed_at else None,
        "booking_id": req.booking_id,
        "created_at": req.created_at.isoformat() if req.created_at else "",
        "resource_name": resource.name if resource else None,
        "resource_type": resource.type if resource else None,
        "resource_building": resource.building if resource else None,
    }


def _can_review_request(
    db: DBSession, reviewer: User, req: BookingRequest, resource: Resource
) -> bool:
    """Return True if the reviewer is authorised to approve/reject this request."""
    if reviewer.role in ("super_admin", "admin"):
        return True

    if reviewer.role == "hod":
        # Campus-wide resources (Auditorium, Playground, Sports Courts) -> reserved exclusively for super_admin/admin
        if resource.type in CAMPUS_RESOURCE_TYPES:
            return False
        if resource.department and reviewer.department == resource.department:
            return True
        return hod_manages_resource(db, reviewer, resource)

    return False


# ---------------------------------------------------------------------------
# Raise a request
# ---------------------------------------------------------------------------

@router.post("/", status_code=201)
def create_request(
    body: RequestCreate,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Submit a booking request.

    Allowed for: cr, club_president, faculty, lab_instructor
    Faculty/lab_instructor raising a request for their OWN dept resource
    should use direct booking (POST /bookings/) instead.
    """
    if user.role not in REQUESTER_ROLES:
        raise HTTPException(
            403,
            detail=f"Role '{user.role}' cannot raise booking requests. "
                   "Use POST /bookings/ for direct bookings."
        )

    # Parse
    try:
        booking_date = date.fromisoformat(body.date)
        start_time   = time.fromisoformat(body.start)
        end_time     = time.fromisoformat(body.end)
    except ValueError:
        raise HTTPException(400, detail="Invalid date or time format (YYYY-MM-DD and HH:MM)")

    resource = db.execute(
        select(Resource).where(Resource.id == body.resource_id)
    ).scalar_one_or_none()

    # Policy check (request-specific)
    check_request_policy(db, user, resource, booking_date, start_time, end_time, body.purpose)

    # Faculty/lab_instructor: if resource is in their OWN dept, tell them to book directly
    if user.role in ("faculty", "lab_instructor"):
        if resource.department and resource.department == user.department:
            raise HTTPException(
                400,
                detail="This resource belongs to your own department. "
                       "Use POST /bookings/ for direct bookings."
            )

    start_dt = datetime.combine(booking_date, start_time)
    end_dt   = datetime.combine(booking_date, end_time)
    ts_range = f"[{start_dt},{end_dt})"

    # Check for duplicate pending request by same user for same slot
    conflict = db.execute(
        text("""
            SELECT id FROM booking_requests
            WHERE requester_id = :uid
              AND resource_id  = :rid
              AND status = 'pending'
              AND during && CAST(:during AS tsrange)
        """),
        {"uid": user.id, "rid": body.resource_id, "during": ts_range}
    ).scalar_one_or_none()
    if conflict:
        raise HTTPException(409, detail="You already have a pending request for this slot")

    req = BookingRequest(
        resource_id=body.resource_id,
        requester_id=user.id,
        during=ts_range,
        purpose=body.purpose.strip(),
        status="pending",
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    write_audit(
        action="booking_request", entity="booking_request", outcome="success",
        actor_id=user.id, entity_id=req.id,
        detail={"resource_id": body.resource_id, "date": body.date,
                "start": body.start, "end": body.end},
        db=db,
    )
    return _request_to_out(req, resource)


# ---------------------------------------------------------------------------
# List requests
# ---------------------------------------------------------------------------

@router.get("/mine")
def list_my_requests(
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List my own booking requests."""
    query = select(BookingRequest, Resource).join(
        Resource, BookingRequest.resource_id == Resource.id
    ).where(BookingRequest.requester_id == user.id)

    if status:
        query = query.where(BookingRequest.status == status)

    offset = (page - 1) * page_size
    rows = db.execute(query.order_by(BookingRequest.created_at.desc())
                      .offset(offset).limit(page_size)).all()
    total = db.execute(
        select(BookingRequest).where(BookingRequest.requester_id == user.id)
    ).scalars().all()

    return {
        "items": [_request_to_out(r, res) for r, res in rows],
        "total": len(total),
        "page": page,
        "page_size": page_size,
    }


@router.get("/pending")
def list_pending_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List pending requests that this user (HOD/admin/super_admin) can review.

    - super_admin / admin: see ALL pending requests
    - hod: see only pending requests for resources in their assigned buildings/depts
    """
    if user.role not in ("super_admin", "admin", "hod"):
        raise HTTPException(403, detail="Only HOD, admin, or super_admin can view pending requests")

    if user.role in ("super_admin", "admin"):
        query = select(BookingRequest, Resource).join(
            Resource, BookingRequest.resource_id == Resource.id
        ).where(BookingRequest.status == "pending")
    else:
        # HOD: resources in their assigned buildings or their department
        assigned = db.execute(
            select(HodBuilding).where(HodBuilding.hod_id == user.id)
        ).scalars().all()

        cond_list = []
        if assigned:
            cond_list.extend([
                (Resource.building == a.building) & (Resource.department == a.department)
                for a in assigned
            ])
        if user.department:
            cond_list.append(Resource.department == user.department)

        if not cond_list:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}

        conditions = or_(*cond_list)
        query = select(BookingRequest, Resource).join(
            Resource, BookingRequest.resource_id == Resource.id
        ).where(
            BookingRequest.status == "pending",
            conditions,
            # HODs don't review campus-wide resource requests (Auditorium, sports, courts, etc)
            Resource.type.notin_(list(CAMPUS_RESOURCE_TYPES)),
        )

    offset = (page - 1) * page_size
    rows = db.execute(
        query.order_by(BookingRequest.created_at.asc())
        .offset(offset).limit(page_size)
    ).all()

    total_rows = db.execute(query).all()

    return {
        "items": [_request_to_out(r, res) for r, res in rows],
        "total": len(total_rows),
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# Review (approve / reject)
# ---------------------------------------------------------------------------

@router.post("/{request_id}/review")
def review_request(
    request_id: int,
    body: ReviewRequest,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Approve or reject a booking request.

    On approval:
      1. Check the slot is still free (no confirmed booking overlaps).
      2. Create a confirmed Booking.
      3. Set request status = 'approved' + booking_id.

    On rejection:
      1. Set request status = 'rejected' + review_note.
    """
    if user.role not in ("super_admin", "admin", "hod"):
        raise HTTPException(403, detail="Only HOD, admin, or super_admin can review requests")

    req = db.execute(
        select(BookingRequest).where(BookingRequest.id == request_id)
    ).scalar_one_or_none()
    if not req:
        raise HTTPException(404, detail="Request not found")

    if req.status != "pending":
        raise HTTPException(400, detail=f"Request is already '{req.status}'")

    resource = db.execute(
        select(Resource).where(Resource.id == req.resource_id)
    ).scalar_one_or_none()
    if not resource:
        raise HTTPException(404, detail="Resource not found")

    # Permission check
    if not _can_review_request(db, user, req, resource):
        raise HTTPException(
            403,
            detail="You are not authorised to review requests for this resource"
        )

    now = datetime.now()
    req.reviewed_by = user.id
    req.reviewed_at = now

    if not body.approve:
        # Rejection
        req.status = "rejected"
        req.review_note = body.note or "Rejected by reviewer"
        db.commit()
        write_audit(
            action="reject_request", entity="booking_request", outcome="success",
            actor_id=user.id, entity_id=request_id,
            detail={"note": req.review_note},
            db=db,
        )
        return {"id": request_id, "status": "rejected"}

    # Approval: check slot is still free
    slot_taken = db.execute(
        text("""
            SELECT id FROM bookings
            WHERE resource_id = :rid
              AND status = 'confirmed'
              AND during && CAST(:during AS tsrange)
        """),
        {"rid": req.resource_id, "during": str(req.during)}
    ).scalar_one_or_none()

    if slot_taken:
        req.status = "rejected"
        req.review_note = "Slot no longer available (conflict with existing booking)"
        db.commit()
        raise HTTPException(
            409,
            detail="Slot is no longer available. Request has been auto-rejected."
        )

    # Create confirmed booking
    try:
        result = db.execute(
            text("""
                INSERT INTO bookings
                  (resource_id, user_id, during, source, status, purpose)
                VALUES
                  (:resource_id, :user_id, CAST(:during AS tsrange),
                   'request', 'confirmed', :purpose)
                RETURNING id
            """),
            {
                "resource_id": req.resource_id,
                "user_id": req.requester_id,
                "during": str(req.during),
                "purpose": req.purpose,
            }
        )
        booking_id = result.scalar_one()
    except IntegrityError:
        db.rollback()
        req.status = "rejected"
        req.review_note = "Slot conflict detected during booking creation"
        db.commit()
        raise HTTPException(409, detail="Slot conflict — request auto-rejected")

    req.status = "approved"
    req.review_note = body.note
    req.booking_id = booking_id
    db.commit()

    write_audit(
        action="approve_request", entity="booking_request", outcome="success",
        actor_id=user.id, entity_id=request_id,
        detail={"booking_id": booking_id},
        db=db,
    )
    return {"id": request_id, "status": "approved", "booking_id": booking_id}


# ---------------------------------------------------------------------------
# Cancel own pending request
# ---------------------------------------------------------------------------

@router.delete("/{request_id}")
def cancel_request(
    request_id: int,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Cancel a pending request (requester only)."""
    req = db.execute(
        select(BookingRequest).where(BookingRequest.id == request_id)
    ).scalar_one_or_none()
    if not req:
        raise HTTPException(404, detail="Request not found")
    if req.requester_id != user.id:
        raise HTTPException(403, detail="You can only cancel your own requests")
    if req.status != "pending":
        raise HTTPException(400, detail=f"Cannot cancel a '{req.status}' request")

    req.status = "rejected"
    req.review_note = "Cancelled by requester"
    req.reviewed_by = user.id
    req.reviewed_at = datetime.now()
    db.commit()

    write_audit(
        action="cancel_request", entity="booking_request", outcome="success",
        actor_id=user.id, entity_id=request_id,
        detail={},
        db=db,
    )
    return {"id": request_id, "status": "cancelled"}
