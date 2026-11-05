from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Date, Time,
    ForeignKey, UniqueConstraint, CheckConstraint, JSON
)
from sqlalchemy.dialects.postgresql import TSRANGE
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db import Base

# ---------------------------------------------------------------------------
# Valid roles (enforced at application layer, not DB enum for easy migration)
# ---------------------------------------------------------------------------
VALID_ROLES = {
    "super_admin",    # God mode: manages entire campus
    "admin",          # Adds resources/users, approves clubs
    "hod",            # Department head: direct book + approves requests in dept
    "faculty",        # Direct book own dept; cross-dept via request
    "lab_instructor", # Direct book own dept labs; cross-dept via request
    "cr",             # Class Representative: request-only for own branch classrooms/labs
    "club_president", # Club head: request any resource; needs approved club
    # NOTE: CR and club_president are FULLY INDEPENDENT roles.
    # A regular student (non-CR) can be a club_president.
    # A CR cannot simultaneously be a club_president (one email = one role).
    "student",        # Regular student: view-only; no booking or requesting
}

# club_president is just a student who leads a club.
# They are NOT required to be a CR. CR and club_president don't imply each other.

# Resource types
RESOURCE_TYPES = {
    "classroom", "lab", "project_space", "seminar_hall",
    "auditorium", "sports", "research_center", "club_room",
}

# Campus-wide resources — only super_admin can directly book or approve
CAMPUS_RESOURCE_TYPES = {"auditorium", "sports", "club_room"}

# Resources CR can request (own branch only)
CR_REQUESTABLE_TYPES = {"classroom", "lab"}

# Roles that can directly book without a request
DIRECT_BOOK_ROLES = {"super_admin", "admin", "hod", "faculty", "lab_instructor"}


class DemoNaive(Base):
    __tablename__ = "demo_naive"
    id     = Column(Integer, primary_key=True)
    room   = Column(String, nullable=False)
    during = Column(TSRANGE, nullable=False)
    who    = Column(String, nullable=False)


class DemoProtected(Base):
    __tablename__ = "demo_protected"
    id     = Column(Integer, primary_key=True)
    room   = Column(String, nullable=False)
    during = Column(TSRANGE, nullable=False)
    who    = Column(String, nullable=False)
    # EXCLUDE constraint added in migration via raw SQL


class Club(Base):
    __tablename__ = "clubs"
    id           = Column(Integer, primary_key=True)
    name         = Column(String, nullable=False, unique=True)
    description  = Column(String, nullable=True)
    president_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_active    = Column(Boolean, default=False, nullable=False)
    created_at   = Column(DateTime, server_default=func.now(), nullable=False)

    president  = relationship("User", foreign_keys=[president_id])
    __table_args__ = (UniqueConstraint("name", name="uq_club_name"),)


class User(Base):
    __tablename__ = "users"
    id            = Column(Integer, primary_key=True)
    email         = Column(String, unique=True, nullable=False, index=True)
    name          = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    # role: one of VALID_ROLES above — one email, one role, no dual hats
    role          = Column(String, nullable=False)
    department    = Column(String, nullable=True)
    # For CR: branch (e.g. "CSE") and division (e.g. "A")
    branch        = Column(String, nullable=True)
    division      = Column(String, nullable=True)
    # For club_president: FK to their registered club
    club_id       = Column(Integer, ForeignKey("clubs.id"), nullable=True)
    created_at    = Column(DateTime, server_default=func.now(), nullable=False)

    club = relationship("Club", foreign_keys=[club_id])


class Session(Base):
    __tablename__ = "sessions"
    token_hash = Column(String, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    user       = relationship("User")


class HodBuilding(Base):
    """Maps a HOD to buildings/departments they manage.
    A building can appear multiple times (once per dept HOD).
    A HOD can appear multiple times (one per building they manage).
    """
    __tablename__ = "hod_buildings"
    id         = Column(Integer, primary_key=True)
    hod_id     = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    building   = Column(String, nullable=False)
    department = Column(String, nullable=False)
    hod        = relationship("User")
    __table_args__ = (
        UniqueConstraint("hod_id", "building", "department", name="uq_hod_building_dept"),
    )


class Resource(Base):
    __tablename__ = "resources"
    id         = Column(Integer, primary_key=True)
    name       = Column(String, nullable=False)
    building   = Column(String, nullable=False)
    floor      = Column(Integer, nullable=False)
    type       = Column(String, nullable=False)
    # classroom, lab, project_space, research_center, seminar_hall,
    # auditorium, sports, club_room
    department = Column(String, nullable=True)   # NULL = campus-wide / shared
    capacity   = Column(Integer, nullable=True)
    is_active  = Column(Boolean, default=True, nullable=False)
    __table_args__ = (UniqueConstraint("building", "name", name="uq_resource_building_name"),)


class Policy(Base):
    __tablename__ = "policies"
    id               = Column(Integer, primary_key=True)
    resource_type    = Column(String, nullable=False)
    actor_kind       = Column(String, nullable=False)
    # actor_kind: super_admin, admin, hod, faculty, lab_instructor, cr, club_president
    allowed          = Column(Boolean, nullable=False)
    condition        = Column(String, nullable=False)
    # direct, own_dept, needs_guide, needs_coordinator, request_only
    max_minutes      = Column(Integer, nullable=False)
    max_advance_days = Column(Integer, nullable=False)
    quota_active     = Column(Integer, nullable=False)
    __table_args__ = (UniqueConstraint("resource_type", "actor_kind", name="uq_policy_type_actor"),)


class Booking(Base):
    __tablename__ = "bookings"
    id           = Column(Integer, primary_key=True)
    resource_id  = Column(Integer, ForeignKey("resources.id"), nullable=False, index=True)
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    during       = Column(TSRANGE, nullable=False)
    source       = Column(String, nullable=False, default="user")
    # source: user, timetable, block, request (approved via booking_requests)
    status       = Column(String, nullable=False, default="confirmed")
    # status: confirmed, cancelled
    purpose      = Column(String, nullable=True)
    faculty_ref_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    course       = Column(String, nullable=True)
    created_at   = Column(DateTime, server_default=func.now(), nullable=False)
    cancelled_at = Column(DateTime, nullable=True)
    cancelled_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    cancel_reason = Column(String, nullable=True)

    resource    = relationship("Resource")
    user        = relationship("User", foreign_keys=[user_id])
    faculty_ref = relationship("User", foreign_keys=[faculty_ref_id])
    canceller   = relationship("User", foreign_keys=[cancelled_by])
    # EXCLUDE constraint added in migration via raw SQL


class BookingRequest(Base):
    """Pending resource requests from CR, club_president, or cross-dept faculty.
    On approval a real Booking is created and booking_id is set.
    """
    __tablename__ = "booking_requests"
    id           = Column(Integer, primary_key=True)
    resource_id  = Column(Integer, ForeignKey("resources.id"), nullable=False, index=True)
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    during       = Column(TSRANGE, nullable=False)
    purpose      = Column(String, nullable=False)
    status       = Column(String, nullable=False, default="pending")
    # status: pending, approved, rejected
    reviewed_by  = Column(Integer, ForeignKey("users.id"), nullable=True)
    review_note  = Column(String, nullable=True)
    reviewed_at  = Column(DateTime, nullable=True)
    booking_id   = Column(Integer, ForeignKey("bookings.id"), nullable=True)
    created_at   = Column(DateTime, server_default=func.now(), nullable=False)

    resource  = relationship("Resource")
    requester = relationship("User", foreign_keys=[requester_id])
    reviewer  = relationship("User", foreign_keys=[reviewed_by])
    booking   = relationship("Booking")


class Term(Base):
    __tablename__ = "terms"
    id         = Column(Integer, primary_key=True)
    name       = Column(String, nullable=False, unique=True)
    start_date = Column(Date, nullable=False)
    end_date   = Column(Date, nullable=False)


class CalendarException(Base):
    __tablename__ = "calendar_exceptions"
    id         = Column(Integer, primary_key=True)
    date       = Column(Date, nullable=False)
    reason     = Column(String, nullable=False)
    is_holiday = Column(Boolean, nullable=False, default=True)


class TimetableSlot(Base):
    __tablename__ = "timetable_slots"
    id         = Column(Integer, primary_key=True)
    term_id    = Column(Integer, ForeignKey("terms.id"), nullable=False)
    weekday    = Column(Integer, nullable=False)   # 1=Mon..7=Sun
    start_time = Column(Time, nullable=False)
    end_time   = Column(Time, nullable=False)
    resource_id = Column(Integer, ForeignKey("resources.id"), nullable=False)
    course     = Column(String, nullable=True)
    faculty_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    term       = relationship("Term")
    resource   = relationship("Resource")
    faculty    = relationship("User")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id        = Column(Integer, primary_key=True)
    at        = Column(DateTime, server_default=func.now(), nullable=False)
    actor_id  = Column(Integer, ForeignKey("users.id"), nullable=True)
    action    = Column(String, nullable=False)
    entity    = Column(String, nullable=False)
    entity_id = Column(Integer, nullable=True)
    outcome   = Column(String, nullable=False)
    detail    = Column(JSON, nullable=True)
