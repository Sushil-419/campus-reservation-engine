"""Clubs router: club registration requests and club info.

Club registration flow:
  1. ANY student (whether CR or not — these are independent roles) can submit
     a club registration request via POST /clubs/register.
  2. The request goes to admin/super_admin who reviews it.
  3. On approval:
       a. Admin approves the club via PATCH /admin/clubs/{id}/approve
       b. Admin changes the student's role to 'club_president' via
          PATCH /admin/users/{id}/role  {role: "club_president"}
       c. Admin links the club to the user via PATCH /admin/users/{id}/role
  4. The user (now club_president) can make booking requests for any resource.

Important: CR and club_president are FULLY INDEPENDENT.
  - A regular student (non-CR) can be a club_president.
  - A CR cannot be a club_president simultaneously (one email = one role).
  - Being a CR does NOT make you a club_president and vice versa.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.db import get_db
from app.models import User, Club
from app.auth import get_current_user
from app.audit import write_audit

router = APIRouter(prefix="/clubs", tags=["clubs"])


class ClubRegisterRequest(BaseModel):
    name: str
    description: str | None = None
    # The email of the student who will be the president.
    # This is submitted to admin for review — admin then sets that
    # student's role to 'club_president' on approval.
    president_email: str


@router.post("/register", status_code=201)
def register_club(
    body: ClubRegisterRequest,
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Submit a club registration request.

    Who can submit: ANY student (role='student'), CR (role='cr'), or existing
    club_president registering a second club (not allowed — one club per president).

    The submitter proposes a president_email. This can be themselves or another
    student. Admin reviews and decides:
      - Approve → club is activated, president_email user gets role='club_president'
      - Reject  → request closed

    CR and club_president are independent — a non-CR student can be president.
    """
    # Only students or CRs can submit club registration requests.
    # (faculty/HOD/admin manage things differently)
    if current.role not in ("student", "cr"):
        raise HTTPException(
            403,
            detail=(
                "Only students (including non-CR students) can submit club "
                "registration requests. "
                "If you are already a club_president, contact admin to register "
                "an additional club."
            )
        )

    # Validate proposed president
    president = db.execute(
        select(User).where(User.email == body.president_email)
    ).scalar_one_or_none()
    if not president:
        raise HTTPException(404, detail=f"No user found with email '{body.president_email}'")

    # President must be a student or CR (not faculty/hod/etc.)
    if president.role not in ("student", "cr"):
        raise HTTPException(
            400,
            detail=(
                f"Proposed president has role '{president.role}'. "
                "Club president must be a student (CR or non-CR). "
                "CR and club_president are independent roles — a non-CR student "
                "can absolutely be a club president."
            )
        )

    # Proposed president must not already be a club_president
    if president.club_id:
        raise HTTPException(
            400,
            detail=f"User '{body.president_email}' is already associated with a club"
        )

    # Club name must be unique
    if not body.name or len(body.name.strip()) < 3:
        raise HTTPException(400, detail="Club name must be at least 3 characters")

    exists = db.execute(
        select(Club).where(Club.name == body.name.strip())
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(400, detail=f"A club named '{body.name}' already exists")

    club = Club(
        name=body.name.strip(),
        description=body.description,
        president_id=president.id,
        is_active=False,  # Pending admin approval
    )
    db.add(club)
    db.commit()
    db.refresh(club)

    write_audit(
        action="club_register_request", entity="club", outcome="success",
        actor_id=current.id, entity_id=club.id,
        detail={
            "club_name": body.name,
            "submitted_by": current.email,
            "proposed_president": body.president_email,
        },
        db=db,
    )
    return {
        "id": club.id,
        "name": club.name,
        "is_active": club.is_active,
        "president_email": body.president_email,
        "message": (
            "Club registration submitted. Pending admin approval. "
            "On approval, the proposed president will be assigned the "
            "'club_president' role by admin."
        ),
    }


@router.get("/mine")
def get_my_club(
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get the club associated with the current club_president."""
    if current.role != "club_president":
        raise HTTPException(403, detail="Only club presidents can view their club")
    if not current.club_id:
        raise HTTPException(404, detail="No club associated with this account")

    club = db.execute(
        select(Club).where(Club.id == current.club_id)
    ).scalar_one_or_none()
    if not club:
        raise HTTPException(404, detail="Club not found")

    return {
        "id": club.id,
        "name": club.name,
        "description": club.description,
        "is_active": club.is_active,
        "created_at": club.created_at.isoformat() if club.created_at else "",
    }


@router.get("/")
def list_all_clubs(
    db: DBSession = Depends(get_db),
):
    """Public endpoint — list all active clubs."""
    rows = db.execute(
        select(Club).where(Club.is_active == True)
    ).scalars().all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "description": c.description,
        }
        for c in rows
    ]
