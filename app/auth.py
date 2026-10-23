"""Authentication: bcrypt passwords, server-side sessions with SHA-256 token hashing.

Session flow:
  1. Login: generate random token, SHA-256 hash it, store hash in DB, send raw token in cookie
  2. Each request: read cookie, SHA-256 hash it, look up session row
  3. Logout: delete session row, clear cookie
  4. Expiry: 8 hours
"""
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, delete
from sqlalchemy.orm import Session as DBSession

from app.db import get_db
from app.models import User, Session

SESSION_TTL_HOURS = 8


def hash_password(plain: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _token_hash(token: str) -> str:
    """SHA-256 hash of a session token (for DB lookup)."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: DBSession, user_id: int) -> str:
    """Create a new session and return the raw token (for cookie)."""
    token = secrets.token_urlsafe(32)
    th = _token_hash(token)
    expires = datetime.now() + timedelta(hours=SESSION_TTL_HOURS)
    sess = Session(token_hash=th, user_id=user_id, expires_at=expires)
    db.add(sess)
    db.commit()
    return token


def delete_session(db: DBSession, token: str) -> None:
    """Delete a session by raw token."""
    th = _token_hash(token)
    db.execute(delete(Session).where(Session.token_hash == th))
    db.commit()


def get_current_user(request: Request, db: DBSession = Depends(get_db)) -> User:
    """FastAPI dependency: extract user from session cookie. Raises 401 if invalid."""
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(401, detail="Not authenticated")
    th = _token_hash(token)
    sess = db.execute(
        select(Session).where(Session.token_hash == th)
    ).scalar_one_or_none()
    if not sess or sess.expires_at < datetime.now():
        raise HTTPException(401, detail="Session expired or invalid")
    user = db.execute(
        select(User).where(User.id == sess.user_id)
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(401, detail="User not found")
    return user


def get_optional_user(request: Request, db: DBSession = Depends(get_db)) -> Optional[User]:
    """Like get_current_user but returns None instead of raising 401."""
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None
