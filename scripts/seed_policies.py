"""Seed the policies table with authorization rules for all 7 roles.

New roles: super_admin, admin, hod, faculty, lab_instructor, cr, club_president

Direct-booking roles: super_admin, admin, hod, faculty, lab_instructor
Request-only roles: cr, club_president
  (their entries here define limits for requests, not direct bookings)

Run: python -m scripts.seed_policies
"""
from app.db import SessionLocal
from app.models import Policy


# Limits by resource type
LIMITS = {
    "classroom":       {"max_minutes": 120, "max_advance_days": 7},
    "sports":          {"max_minutes": 120, "max_advance_days": 7},
    "lab":             {"max_minutes": 180, "max_advance_days": 14},
    "project_space":   {"max_minutes": 180, "max_advance_days": 14},
    "research_center": {"max_minutes": 180, "max_advance_days": 14},
    "seminar_hall":    {"max_minutes": 240, "max_advance_days": 30},
    "auditorium":      {"max_minutes": 240, "max_advance_days": 30},
    "club_room":       {"max_minutes": 180, "max_advance_days": 14},
}

# Quota of active confirmed bookings per actor_kind
QUOTA = {
    "super_admin":    99,
    "admin":          20,
    "hod":            10,
    "faculty":         5,
    "lab_instructor":  5,
    "cr":              3,   # requests, not direct bookings
    "club_president":  3,   # requests, not direct bookings
    "student":         0,   # view-only: no bookings or requests
}

# Policy matrix: (resource_type, actor_kind) -> (allowed, condition)
#
# condition values:
#   direct           — no extra conditions; book freely
#   own_dept         — resource.department must match user.department
#   needs_guide      — faculty_ref_email required
#   needs_coordinator— faculty_ref_email + purpose (≥10 chars) required
#   request_only     — this role MUST go through booking_requests (enforced in policy.py)
#
# Note: cr and club_president rows with condition='request_only' document
#       what types they can request; actual enforcement is in policy.py.

MATRIX = [
    # ---- classroom ----
    ("classroom", "super_admin",    True,  "direct"),
    ("classroom", "admin",          True,  "direct"),
    ("classroom", "hod",            True,  "direct"),
    ("classroom", "faculty",        True,  "own_dept"),       # cross-dept → request_only
    ("classroom", "lab_instructor", True,  "own_dept"),
    ("classroom", "cr",             True,  "request_only"),   # via booking_requests
    ("classroom", "club_president", True,  "request_only"),

    # ---- lab ----
    ("lab", "super_admin",    True,  "direct"),
    ("lab", "admin",          True,  "direct"),
    ("lab", "hod",            True,  "direct"),
    ("lab", "faculty",        True,  "own_dept"),
    ("lab", "lab_instructor", True,  "own_dept"),
    ("lab", "cr",             True,  "request_only"),
    ("lab", "club_president", True,  "request_only"),

    # ---- project_space ----
    ("project_space", "super_admin",    True,  "direct"),
    ("project_space", "admin",          True,  "direct"),
    ("project_space", "hod",            True,  "direct"),
    ("project_space", "faculty",        True,  "own_dept"),
    ("project_space", "lab_instructor", True,  "own_dept"),
    ("project_space", "cr",             False, "request_only"),  # CR NOT allowed even by request
    ("project_space", "club_president", True,  "request_only"),

    # ---- research_center ----
    ("research_center", "super_admin",    True,  "direct"),
    ("research_center", "admin",          True,  "direct"),
    ("research_center", "hod",            True,  "direct"),
    ("research_center", "faculty",        True,  "needs_guide"),
    ("research_center", "lab_instructor", False, "direct"),    # NOT ALLOWED at all
    ("research_center", "cr",             False, "request_only"),
    ("research_center", "club_president", False, "request_only"),

    # ---- seminar_hall ----
    ("seminar_hall", "super_admin",    True,  "direct"),
    ("seminar_hall", "admin",          True,  "direct"),
    ("seminar_hall", "hod",            True,  "direct"),
    ("seminar_hall", "faculty",        True,  "own_dept"),
    ("seminar_hall", "lab_instructor", True,  "own_dept"),
    ("seminar_hall", "cr",             False, "request_only"),
    ("seminar_hall", "club_president", True,  "request_only"),

    # ---- auditorium (campus-wide, super_admin direct only) ----
    ("auditorium", "super_admin",    True,  "direct"),
    ("auditorium", "admin",          False, "direct"),         # admin cannot book directly
    ("auditorium", "hod",            False, "direct"),         # HOD cannot book auditorium
    ("auditorium", "faculty",        False, "direct"),
    ("auditorium", "lab_instructor", False, "direct"),
    ("auditorium", "cr",             False, "request_only"),
    ("auditorium", "club_president", True,  "request_only"),   # club can request auditorium

    # ---- sports / courts / playground (campus-wide) ----
    ("sports", "super_admin",    True,  "direct"),
    ("sports", "admin",          False, "direct"),
    ("sports", "hod",            False, "direct"),
    ("sports", "faculty",        True,  "own_dept"),           # faculty can book for dept events
    ("sports", "lab_instructor", False, "direct"),
    ("sports", "cr",             False, "request_only"),
    ("sports", "club_president", True,  "request_only"),

    # ---- club_room (campus-wide) ----
    ("club_room", "super_admin",    True,  "direct"),
    ("club_room", "admin",          False, "direct"),
    ("club_room", "hod",            False, "direct"),
    ("club_room", "faculty",        False, "direct"),
    ("club_room", "lab_instructor", False, "direct"),
    ("club_room", "cr",             False, "request_only"),
    ("club_room", "club_president", True,  "request_only"),    # club can request club_room
]


def seed_policies():
    db = SessionLocal()
    try:
        existing = db.query(Policy).count()
        if existing > 0:
            print(f"Policies table already has {existing} rows — skipping.")
            return

        rows = []
        for resource_type, actor_kind, allowed, condition in MATRIX:
            limits = LIMITS[resource_type]
            quota  = QUOTA[actor_kind]
            rows.append(Policy(
                resource_type=resource_type,
                actor_kind=actor_kind,
                allowed=allowed,
                condition=condition,
                max_minutes=limits["max_minutes"],
                max_advance_days=limits["max_advance_days"],
                quota_active=quota,
            ))

        db.add_all(rows)
        db.commit()
        print(f"Seeded {len(rows)} policy rows.")

        for rt in LIMITS:
            count = sum(1 for r in rows if r.resource_type == rt)
            print(f"  {rt}: {count} actor rules")
    finally:
        db.close()


if __name__ == "__main__":
    seed_policies()
