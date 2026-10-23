"""Auth router: register, login, logout, me."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.db import get_db
from app.models import User
from app.auth import (
    hash_password, verify_password, create_session, delete_session,
    get_current_user,
)
from app.audit import write_audit

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str
    password: str
    role: str = "student"
    department: str | None = None
    is_cr: bool = False


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    is_cr: bool
    department: str | None

    model_config = {"from_attributes": True}


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterRequest, db: DBSession = Depends(get_db)):
    """Register a new user."""
    existing = db.execute(
        select(User.id).where(User.email == body.email)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(400, detail="Email already registered")

    if body.role not in ("student", "faculty", "lab_instructor", "hod"):
        raise HTTPException(400, detail="Invalid role")

    user = User(
        email=body.email,
        name=body.name,
        password_hash=hash_password(body.password),
        role=body.role,
        is_cr=body.is_cr,
        department=body.department,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    write_audit(
        action="register", entity="user", outcome="success",
        actor_id=user.id, entity_id=user.id,
        detail={"email": body.email},
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
