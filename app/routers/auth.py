"""Auth router: register, login, logout, me."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.db import get_db
from app.models import User, VALID_ROLES
from app.auth import (
    hash_password, verify_password, create_session, delete_session,
    get_current_user,
)
from app.audit import write_audit

router = APIRouter(prefix="/auth", tags=["auth"])

# Roles that can self-register (without admin intervention)
# NOTE: CR and club_president are completely independent roles.
# A regular student (non-CR) can become a club_president.
# Neither implies the other — one email = one role, but any student
# regardless of being CR or not can be assigned club_president by admin.
SELF_REGISTER_ROLES = {"student", "faculty", "lab_instructor", "cr"}

# Roles that require admin/super_admin to create
ADMIN_ONLY_ROLES = {"super_admin", "admin", "hod", "club_president"}


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str
    password: str
    role: str = "faculty"
    department: str | None = None
    # For CR
    branch: str | None = None
    division: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    department: str | None
    branch: str | None = None
    division: str | None = None
    club_id: int | None = None

    model_config = {"from_attributes": True}


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterRequest, db: DBSession = Depends(get_db)):
    """Self-register for faculty, lab_instructor, or CR.
    HOD, admin, super_admin, and club_president must be created by an admin.
    """
    existing = db.execute(
        select(User.id).where(User.email == body.email)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(400, detail="Email already registered")

    if body.role not in VALID_ROLES:
        raise HTTPException(400, detail=f"Invalid role. Must be one of: {sorted(VALID_ROLES)}")

    if body.role in ADMIN_ONLY_ROLES:
        raise HTTPException(
            403,
            detail=f"Role '{body.role}' must be assigned by an admin. "
                   "Contact your system administrator."
        )

    # CR must provide branch and division
    if body.role == "cr":
        if not body.branch:
            raise HTTPException(400, detail="CR must provide their branch (e.g. 'CSE')")
        if not body.division:
            raise HTTPException(400, detail="CR must provide their division (e.g. 'A')")

    user = User(
        email=body.email,
        name=body.name,
        password_hash=hash_password(body.password),
        role=body.role,
        department=body.department,
        branch=body.branch,
        division=body.division,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    write_audit(
        action="register", entity="user", outcome="success",
        actor_id=user.id, entity_id=user.id,
        detail={"email": body.email, "role": body.role},
        db=db,
    )
    return user


@router.post("/login")
def login(body: LoginRequest, response: Response, db: DBSession = Depends(get_db)):
    """Log in and set session cookie."""
    user = db.execute(
        select(User).where(User.email == body.email)
    ).scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        write_audit(
            action="login_fail", entity="session", outcome="fail",
            detail={"email": body.email},
            db=db,
        )
        raise HTTPException(401, detail="Invalid credentials")

    token = create_session(db, user.id)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=8 * 3600,
    )

    write_audit(
        action="login", entity="session", outcome="success",
        actor_id=user.id,
        db=db,
    )
    return {"message": "Logged in", "user": UserOut.model_validate(user).model_dump()}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Log out: delete session and clear cookie."""
    token = request.cookies.get("session_token")
    if token:
        delete_session(db, token)
    response.delete_cookie("session_token")
    write_audit(
        action="logout", entity="session", outcome="success",
        actor_id=user.id,
    )
    return {"message": "Logged out"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    """Return the currently authenticated user."""
    return user
