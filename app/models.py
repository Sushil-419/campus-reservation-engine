from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Date, Time,
    ForeignKey, UniqueConstraint, CheckConstraint, JSON
)
from sqlalchemy.dialects.postgresql import TSRANGE
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db import Base

class DemoNaive(Base):
    __tablename__ = "demo_naive"
    id = Column(Integer, primary_key=True)
    room = Column(String, nullable=False)
    during = Column(TSRANGE, nullable=False)
    who = Column(String, nullable=False)

class DemoProtected(Base):
    __tablename__ = "demo_protected"
    id = Column(Integer, primary_key=True)
    room = Column(String, nullable=False)
    during = Column(TSRANGE, nullable=False)
    who = Column(String, nullable=False)
    # EXCLUDE constraint added in migration via raw SQL

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # student, faculty, lab_instructor, hod
    is_cr = Column(Boolean, default=False, nullable=False)
    department = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

class Session(Base):
    __tablename__ = "sessions"
    token_hash = Column(String, primary_key=True)  # bcrypt hash of token
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    user = relationship("User")

class Resource(Base):
    __tablename__ = "resources"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    building = Column(String, nullable=False)
    floor = Column(Integer, nullable=False)
    type = Column(String, nullable=False)  # classroom, lab, project_space, research_center, seminar_hall, auditorium, sports
    department = Column(String, nullable=True)  # NULL = shared
    capacity = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    __table_args__ = (UniqueConstraint("building", "name", name="uq_resource_building_name"),)

class Policy(Base):
    __tablename__ = "policies"
    id = Column(Integer, primary_key=True)
    resource_type = Column(String, nullable=False)  # classroom, lab, etc.
    actor_kind = Column(String, nullable=False)  # student, cr, faculty, lab_instructor, hod
    allowed = Column(Boolean, nullable=False)
    condition = Column(String, nullable=False)  # direct, own_dept, needs_guide, needs_coordinator
    max_minutes = Column(Integer, nullable=False)
    max_advance_days = Column(Integer, nullable=False)
    quota_active = Column(Integer, nullable=False)  # max future confirmed source='user' bookings
    __table_args__ = (UniqueConstraint("resource_type", "actor_kind", name="uq_policy_type_actor"),)

class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True)
    resource_id = Column(Integer, ForeignKey("resources.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    during = Column(TSRANGE, nullable=False)
    source = Column(String, nullable=False, default="user")  # user, timetable, block
    status = Column(String, nullable=False, default="confirmed")  # confirmed, cancelled
    purpose = Column(String, nullable=True)
    faculty_ref_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    course = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    cancelled_at = Column(DateTime, nullable=True)
    cancelled_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    cancel_reason = Column(String, nullable=True)

    resource = relationship("Resource")
    user = relationship("User", foreign_keys=[user_id])
    faculty_ref = relationship("User", foreign_keys=[faculty_ref_id])
    canceller = relationship("User", foreign_keys=[cancelled_by])
    # EXCLUDE constraint added in migration via raw SQL

class Term(Base):
    __tablename__ = "terms"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)  # e.g. "2026-odd"
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)

class CalendarException(Base):
    __tablename__ = "calendar_exceptions"
    id = Column(Integer, primary_key=True)
    date = Column(Date, nullable=False)
    reason = Column(String, nullable=False)
    is_holiday = Column(Boolean, nullable=False, default=True)

class TimetableSlot(Base):
    __tablename__ = "timetable_slots"
    id = Column(Integer, primary_key=True)
    term_id = Column(Integer, ForeignKey("terms.id"), nullable=False)
    weekday = Column(Integer, nullable=False)  # 1=Mon..7=Sun
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    resource_id = Column(Integer, ForeignKey("resources.id"), nullable=False)
    course = Column(String, nullable=True)
    faculty_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    term = relationship("Term")
    resource = relationship("Resource")
    faculty = relationship("User")

class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    at = Column(DateTime, server_default=func.now(), nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)  # login, login_fail, register, book, cancel, etc.
    entity = Column(String, nullable=False)  # booking, user, session, etc.
    entity_id = Column(Integer, nullable=True)
    outcome = Column(String, nullable=False)  # success, fail, error
    detail = Column(JSON, nullable=True)
