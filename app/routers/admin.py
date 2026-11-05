"""Admin router: user management, HOD building assignment, resource management.

Who can call what:
  super_admin — everything
  admin       — add users (non-admin roles), add resources, approve clubs
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, func
from sqlalchemy.orm import Session as DBSession

from app.db import get_db
from app.models import User, Resource, HodBuilding, Club, VALID_ROLES
from app.auth import get_current_user, hash_password
from app.audit import write_audit

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------

def _require_admin(user: User) -> None:
    if user.role not in ("super_admin", "admin"):
        raise HTTPException(403, detail="Admin privileges required")


def _require_admin_or_hod(user: User) -> None:
    if user.role not in ("super_admin", "admin", "hod"):
        raise HTTPException(403, detail="Administrative or HOD privileges required")


def _require_super_admin(user: User) -> None:
    if user.role != "super_admin":
        raise HTTPException(403, detail="Super admin privileges required")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CreateUserRequest(BaseModel):
    email: EmailStr
    name: str
    password: str
    role: str
    department: str | None = None
    branch: str | None = None
    division: str | None = None
    club_id: int | None = None


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    department: str | None
    branch: str | None = None
    division: str | None = None
    club_id: int | None = None
    created_at: str

    model_config = {"from_attributes": True}


class PromoteHodRequest(BaseModel):
    user_id: int


class AssignBuildingRequest(BaseModel):
    hod_id: int
    building: str
    department: str


class ResourceCreate(BaseModel):
    name: str
    building: str
    floor: int
    type: str
    department: str | None = None
    capacity: int | None = None


class ClubApproveRequest(BaseModel):
    approve: bool
    note: str | None = None


class AppointCrRequest(BaseModel):
    email: EmailStr
    name: str | None = None
    password: str | None = None
    division: str
    branch: str | None = None


# ---------------------------------------------------------------------------
# CR Appointment & Management (HOD & Admin)
# ---------------------------------------------------------------------------

@router.get("/cr")
def list_class_representatives(
    branch: Optional[str] = None,
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List Class Representatives (CRs).
    - HOD sees only CRs for their branch.
    - Super Admin / Admin can see all CRs or filter by branch.
    """
    if current.role not in ("super_admin", "admin", "hod"):
        raise HTTPException(403, detail="HOD or Admin privileges required")

    query = select(User).where(User.role == "cr")
    if current.role == "hod":
        query = query.where(User.branch == current.department)
    elif branch:
        query = query.where(User.branch == branch)

    rows = db.execute(query.order_by(User.branch, User.division, User.name)).scalars().all()
    return [_user_to_out(u) for u in rows]


@router.post("/cr", status_code=201)
def appoint_class_representative(
    body: AppointCrRequest,
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Appoint or create a Class Representative (CR) for a branch and division.
    - HOD can ONLY appoint CR for their own branch/department.
    - Super Admin / Admin can appoint CR for any branch.
    - Promotes an existing student to CR, or provisions a new CR account.
    - Strictly enforces one email = one role.
    """
    if current.role not in ("super_admin", "admin", "hod"):
        raise HTTPException(403, detail="HOD or Admin privileges required")

    # Determine branch
    if current.role == "hod":
        if not current.department:
            raise HTTPException(400, detail="HOD account has no assigned department")
        assigned_branch = current.department
        if body.branch and body.branch != current.department:
            raise HTTPException(403, detail=f"HOD can only appoint CRs for their own branch ({current.department})")
    else:
        if not body.branch:
            raise HTTPException(400, detail="Branch is required (e.g. CSE, EEE)")
        assigned_branch = body.branch

    if not body.division or not body.division.strip():
        raise HTTPException(400, detail="Division is required (e.g. A, B, C)")

    clean_div = body.division.strip().upper()

    existing = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if existing:
        # User already exists - check role constraint
        if existing.role in ("faculty", "lab_instructor", "hod", "admin", "super_admin"):
            raise HTTPException(
                400,
                detail=f"User '{body.email}' already holds role '{existing.role}'. One user = one role. Cannot appoint staff to CR."
            )
        if existing.role == "club_president":
            raise HTTPException(
                400,
                detail=f"User '{body.email}' is currently a Club President. One user = one role."
            )

        # Promote student or update existing CR
        old_role = existing.role
        existing.role = "cr"
        existing.department = assigned_branch
        existing.branch = assigned_branch
        existing.division = clean_div
        if body.name and body.name.strip():
            existing.name = body.name.strip()
        db.commit()
        db.refresh(existing)

        write_audit(
            action="appoint_cr", entity="user", outcome="success",
            actor_id=current.id, entity_id=existing.id,
            detail={"email": existing.email, "branch": assigned_branch, "division": clean_div, "from_role": old_role},
            db=db,
        )
        return _user_to_out(existing)

    # New user provision
    if not body.name or not body.name.strip():
        raise HTTPException(400, detail="Name is required for new CR accounts")
    if not body.password or len(body.password) < 6:
        raise HTTPException(400, detail="Password with at least 6 characters is required for new accounts")

    new_cr = User(
        email=body.email,
        name=body.name.strip(),
        password_hash=hash_password(body.password),
        role="cr",
        department=assigned_branch,
        branch=assigned_branch,
        division=clean_div,
    )
    db.add(new_cr)
    db.commit()
    db.refresh(new_cr)

    write_audit(
        action="create_cr", entity="user", outcome="success",
        actor_id=current.id, entity_id=new_cr.id,
        detail={"email": new_cr.email, "branch": assigned_branch, "division": clean_div},
        db=db,
    )
    return _user_to_out(new_cr)


@router.delete("/cr/{user_id}")
def revoke_class_representative(
    user_id: int,
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Revoke CR status and return user to regular student role."""
    if current.role not in ("super_admin", "admin", "hod"):
        raise HTTPException(403, detail="HOD or Admin privileges required")

    target = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if not target or target.role != "cr":
        raise HTTPException(404, detail="Class Representative not found")

    if current.role == "hod" and target.branch != current.department:
        raise HTTPException(403, detail="HODs can only manage CRs within their own branch")

    target.role = "student"
    target.division = None
    db.commit()

    write_audit(
        action="revoke_cr", entity="user", outcome="success",
        actor_id=current.id, entity_id=user_id,
        detail={"email": target.email},
        db=db,
    )
    return {"id": user_id, "message": "CR status revoked; user reverted to student"}


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    body: CreateUserRequest,
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Create a user account.
    - HOD: can provision faculty, lab_instructor, and cr accounts within their department.
    - Admin: can provision staff and students across departments.
    - Super Admin: can provision any role, including HOD and Admin.
    """
    _require_admin_or_hod(current)

    if body.role not in VALID_ROLES:
        raise HTTPException(400, detail=f"Invalid role. Valid: {sorted(VALID_ROLES)}")

    # Role constraints by operator
    if current.role == "hod":
        if body.role not in ("faculty", "lab_instructor", "cr"):
            raise HTTPException(403, detail="HOD can only provision faculty, lab_instructor, or cr accounts")
        if not current.department:
            raise HTTPException(400, detail="HOD account has no assigned department")
        body.department = current.department
        body.branch = current.department
    elif current.role == "admin":
        if body.role in ("super_admin", "admin", "hod"):
            raise HTTPException(403, detail="Only super_admin can create admin, super_admin, or hod accounts")
    elif current.role == "super_admin":
        pass

    existing = db.execute(select(User.id).where(User.email == body.email)).scalar_one_or_none()
    if existing:
        raise HTTPException(400, detail="Email already registered")

    # Validate role-specific fields
    if body.role == "cr":
        if not body.branch:
            raise HTTPException(400, detail="CR requires a branch")
        if not body.division:
            raise HTTPException(400, detail="CR requires a division")

    if body.role == "club_president" and body.club_id:
        club = db.execute(select(Club).where(Club.id == body.club_id)).scalar_one_or_none()
        if not club:
            raise HTTPException(404, detail="Club not found")

    user = User(
        email=body.email,
        name=body.name,
        password_hash=hash_password(body.password),
        role=body.role,
        department=body.department,
        branch=body.branch,
        division=body.division,
        club_id=body.club_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    write_audit(
        action="admin_create_user", entity="user", outcome="success",
        actor_id=current.id, entity_id=user.id,
        detail={"email": body.email, "role": body.role, "dept": body.department},
        db=db,
    )
    return _user_to_out(user)


@router.get("/users", response_model=list[UserOut])
def list_users(
    role: Optional[str] = None,
    department: Optional[str] = None,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List users for admin/HOD management.
    - HOD: sees only staff (faculty, lab_instructor), CRs, and students in their department.
    - Super Admin / Admin: sees all users across the campus.
    """
    _require_admin_or_hod(current)
    query = select(User)

    if current.role == "hod":
        from sqlalchemy import or_
        dept = current.department or ""
        query = query.where(
            or_(User.department == dept, User.branch == dept)
        ).where(
            User.role.in_(["faculty", "lab_instructor", "cr", "student"])
        )
    else:
        if department:
            query = query.where(User.department == department)

    if role:
        query = query.where(User.role == role)
    if q:
        query = query.where(User.name.ilike(f"%{q}%") | User.email.ilike(f"%{q}%"))

    offset = (page - 1) * page_size
    rows = db.execute(query.order_by(User.role, User.name).offset(offset).limit(page_size)).scalars().all()
    return [_user_to_out(u) for u in rows]


@router.patch("/users/{user_id}/role")
def change_user_role(
    user_id: int,
    body: dict,
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Change a user's role. Only super_admin can promote to hod/admin/super_admin."""
    _require_super_admin(current)

    new_role = body.get("role")
    if new_role not in VALID_ROLES:
        raise HTTPException(400, detail=f"Invalid role: {new_role}")

    target = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if not target:
        raise HTTPException(404, detail="User not found")
    if target.id == current.id:
        raise HTTPException(400, detail="Cannot change your own role")

    old_role = target.role
    target.role = new_role
    if body.get("department"):
        target.department = body.get("department")
    db.commit()

    write_audit(
        action="change_role", entity="user", outcome="success",
        actor_id=current.id, entity_id=user_id,
        detail={"old_role": old_role, "new_role": new_role},
        db=db,
    )
    return {"id": user_id, "role": new_role}


@router.delete("/users/{user_id}")
def deactivate_user(
    user_id: int,
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Deactivate a user (soft-delete via role set to 'deactivated')."""
    _require_admin_or_hod(current)
    target = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if not target:
        raise HTTPException(404, detail="User not found")
    if target.id == current.id:
        raise HTTPException(400, detail="Cannot deactivate yourself")

    if current.role == "hod":
        if target.department != current.department and target.branch != current.department:
            raise HTTPException(403, detail="HOD can only deactivate staff or students within their own department")
        if target.role in ("super_admin", "admin", "hod"):
            raise HTTPException(403, detail="HOD cannot deactivate administrative accounts")
    elif target.role in ("super_admin", "admin") and current.role != "super_admin":
        raise HTTPException(403, detail="Only super_admin can deactivate admin accounts")

    old_role = target.role
    target.role = "deactivated"
    db.commit()
    write_audit(
        action="deactivate_user", entity="user", outcome="success",
        actor_id=current.id, entity_id=user_id,
        detail={"old_role": old_role},
        db=db,
    )
    return {"id": user_id, "status": "deactivated"}


# ---------------------------------------------------------------------------
# HOD building assignment (super_admin only for changes; HOD can view theirs)
# ---------------------------------------------------------------------------

@router.post("/hod-buildings", status_code=201)
def assign_building_to_hod(
    body: AssignBuildingRequest,
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Assign a building+department to a HOD. super_admin only."""
    _require_super_admin(current)

    hod = db.execute(select(User).where(User.id == body.hod_id)).scalar_one_or_none()
    if not hod:
        raise HTTPException(404, detail="User not found")
    if hod.role != "hod":
        raise HTTPException(400, detail="Target user is not a HOD")

    # Check duplicate
    exists = db.execute(
        select(HodBuilding).where(
            HodBuilding.hod_id == body.hod_id,
            HodBuilding.building == body.building,
            HodBuilding.department == body.department,
        )
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(400, detail="This HOD is already assigned to this building+department")

    assignment = HodBuilding(
        hod_id=body.hod_id,
        building=body.building,
        department=body.department,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)

    write_audit(
        action="assign_building", entity="hod_building", outcome="success",
        actor_id=current.id, entity_id=assignment.id,
        detail={"hod_id": body.hod_id, "building": body.building, "dept": body.department},
        db=db,
    )
    return {"id": assignment.id, "hod_id": body.hod_id,
            "building": body.building, "department": body.department}


@router.get("/hod-buildings")
def list_hod_buildings(
    hod_id: Optional[int] = None,
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List HOD building assignments.
    - HOD: sees only the building complexes and wings allotted to them.
    - Super Admin / Admin: sees all campus allotments.
    """
    _require_admin_or_hod(current)
    query = select(HodBuilding)

    if current.role == "hod":
        query = query.where(HodBuilding.hod_id == current.id)
    elif hod_id:
        query = query.where(HodBuilding.hod_id == hod_id)

    rows = db.execute(query).scalars().all()
    return [
        {"id": r.id, "hod_id": r.hod_id, "building": r.building, "department": r.department}
        for r in rows
    ]


@router.delete("/hod-buildings/{assignment_id}")
def remove_hod_building(
    assignment_id: int,
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Remove a HOD building assignment. super_admin only."""
    _require_super_admin(current)
    row = db.execute(select(HodBuilding).where(HodBuilding.id == assignment_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(404, detail="Assignment not found")
    db.delete(row)
    db.commit()
    return {"id": assignment_id, "status": "removed"}


# ---------------------------------------------------------------------------
# Resource management (admin/super_admin/hod)
# ---------------------------------------------------------------------------

@router.get("/resources")
def list_admin_resources(
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List resources for admin dashboard inventory.
    - HOD: sees only resources belonging to their department or allotted buildings.
    - Super Admin / Admin: sees all campus resources.
    """
    _require_admin_or_hod(current)
    query = select(Resource)

    if current.role == "hod":
        from sqlalchemy import or_
        assigned = db.execute(
            select(HodBuilding).where(HodBuilding.hod_id == current.id)
        ).scalars().all()

        conds = []
        if current.department:
            conds.append(Resource.department == current.department)
        for a in assigned:
            conds.append((Resource.building == a.building) & (Resource.department == a.department))

        if not conds:
            return []
        query = query.where(or_(*conds))

    rows = db.execute(query.order_by(Resource.building, Resource.floor, Resource.name)).scalars().all()
    return [
        {
            "id": r.id, "name": r.name, "building": r.building,
            "floor": r.floor, "type": r.type, "department": r.department,
            "capacity": r.capacity, "is_active": r.is_active,
        }
        for r in rows
    ]


@router.post("/resources", status_code=201)
def add_resource(
    body: ResourceCreate,
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Add a new facility.
    - HOD: can add facilities strictly within their department in their allotted buildings.
    - Admin / Super Admin: can add any facility.
    """
    _require_admin_or_hod(current)

    from app.models import RESOURCE_TYPES, CAMPUS_RESOURCE_TYPES
    if body.type not in RESOURCE_TYPES:
        raise HTTPException(400, detail=f"Invalid resource type. Valid: {sorted(RESOURCE_TYPES)}")

    if current.role == "hod":
        if body.type in CAMPUS_RESOURCE_TYPES:
            raise HTTPException(403, detail="HODs cannot register campus-wide venues (Auditorium, Sports)")
        if not current.department:
            raise HTTPException(400, detail="HOD account has no assigned department")
        body.department = current.department

        # Verify that this building complex is allotted to this HOD
        allotted = db.execute(
            select(HodBuilding).where(
                HodBuilding.hod_id == current.id,
                HodBuilding.building == body.building,
                HodBuilding.department == current.department,
            )
        ).scalar_one_or_none()
        if not allotted:
            raise HTTPException(
                403,
                detail=f"Building '{body.building}' has not been allotted to your department ({current.department}) by Super Admin."
            )

    resource = Resource(
        name=body.name,
        building=body.building,
        floor=body.floor,
        type=body.type,
        department=body.department,
        capacity=body.capacity,
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    write_audit(
        action="add_resource", entity="resource", outcome="success",
        actor_id=current.id, entity_id=resource.id,
        detail={"name": body.name, "building": body.building, "type": body.type, "dept": body.department},
        db=db,
    )
    return {"id": resource.id, "name": resource.name, "building": resource.building,
            "floor": resource.floor, "type": resource.type, "department": resource.department}


@router.patch("/resources/{resource_id}/toggle")
def toggle_resource(
    resource_id: int,
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Activate or deactivate a resource."""
    _require_admin_or_hod(current)
    resource = db.execute(select(Resource).where(Resource.id == resource_id)).scalar_one_or_none()
    if not resource:
        raise HTTPException(404, detail="Resource not found")

    if current.role == "hod":
        from app.policy import hod_manages_resource
        if not hod_manages_resource(db, current, resource):
            raise HTTPException(403, detail="HODs can only toggle resources under their assigned department/building")

    resource.is_active = not resource.is_active
    db.commit()
    return {"id": resource_id, "is_active": resource.is_active}


# ---------------------------------------------------------------------------
# Club management (super_admin / admin / hod)
# ---------------------------------------------------------------------------

@router.get("/clubs")
def list_clubs(
    is_active: Optional[bool] = None,
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List all clubs for review."""
    _require_admin_or_hod(current)
    query = select(Club)
    if is_active is not None:
        query = query.where(Club.is_active == is_active)
    rows = db.execute(query).scalars().all()
    return [_club_out(c) for c in rows]


@router.patch("/clubs/{club_id}/approve")
def approve_club(
    club_id: int,
    body: ClubApproveRequest,
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Approve or reject a club registration (HOD, admin, or super_admin).

    On approval:
      - Club is_active set to True
      - The club's president_id user is promoted to role='club_president'
      - Their club_id is linked to this club
    """
    _require_admin_or_hod(current)
    club = db.execute(select(Club).where(Club.id == club_id)).scalar_one_or_none()
    if not club:
        raise HTTPException(404, detail="Club not found")

    if body.approve:
        # Promote the president user
        if club.president_id:
            president = db.execute(
                select(User).where(User.id == club.president_id)
            ).scalar_one_or_none()

            if president:
                # Block: CR cannot hold both roles (one email = one role)
                if president.role == "cr":
                    raise HTTPException(
                        400,
                        detail=(
                            f"Proposed president '{president.email}' is currently a CR. "
                            "One email = one role. They must give up CR role to become "
                            "club_president. Ask them or admin to change their role first."
                        )
                    )
                if president.role not in ("student", "cr", "club_president"):
                    raise HTTPException(
                        400,
                        detail=f"Cannot promote role='{president.role}' to club_president"
                    )
                # Promote to club_president and link club
                president.role = "club_president"
                president.club_id = club.id

        club.is_active = True
    else:
        club.is_active = False

    db.commit()

    action = "approve_club" if body.approve else "reject_club"
    write_audit(
        action=action, entity="club", outcome="success",
        actor_id=current.id, entity_id=club_id,
        detail={"club_name": club.name, "note": body.note},
        db=db,
    )
    return {"id": club_id, "is_active": club.is_active, "name": club.name}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_to_out(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "role": u.role,
        "department": u.department,
        "branch": u.branch,
        "division": u.division,
        "club_id": u.club_id,
        "created_at": u.created_at.isoformat() if u.created_at else "",
    }


def _club_out(c: Club) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "president_id": c.president_id,
        "is_active": c.is_active,
        "created_at": c.created_at.isoformat() if c.created_at else "",
    }
