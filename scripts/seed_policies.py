"""Seed the policies table with authorization rules.

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
}

# Quota by actor_kind
QUOTA = {
    "student": 2,
    "cr": 3,
    "faculty": 5,
    "lab_instructor": 5,
    "hod": 10,
}

# Policy matrix: (resource_type, actor_kind) -> (allowed, condition)
# Missing entries (like CR for project_space) mean no row — CR falls back to student.
MATRIX = [
    # classroom
    ("classroom", "student",        True,  "needs_coordinator"),
    ("classroom", "cr",             True,  "own_dept"),
    ("classroom", "faculty",        True,  "direct"),
    ("classroom", "lab_instructor", True,  "own_dept"),
    ("classroom", "hod",            True,  "direct"),
    # project_space (tinkering lab, DTSI)
    ("project_space", "student",        True,  "needs_guide"),
    ("project_space", "faculty",        True,  "direct"),
    ("project_space", "lab_instructor", True,  "direct"),
    ("project_space", "hod",            True,  "direct"),
    # lab
    ("lab", "student",        True,  "needs_guide"),
    ("lab", "faculty",        True,  "direct"),
    ("lab", "lab_instructor", True,  "own_dept"),
    ("lab", "hod",            True,  "direct"),
    # research_center
    ("research_center", "student",        True,  "needs_guide"),
    ("research_center", "faculty",        True,  "direct"),
    ("research_center", "lab_instructor", False, "direct"),  # NOT ALLOWED
    ("research_center", "hod",            True,  "direct"),
    # seminar_hall
    ("seminar_hall", "student",        True,  "needs_coordinator"),
    ("seminar_hall", "faculty",        True,  "direct"),
    ("seminar_hall", "lab_instructor", True,  "own_dept"),
    ("seminar_hall", "hod",            True,  "direct"),
    # auditorium
    ("auditorium", "student",        True,  "needs_coordinator"),
    ("auditorium", "faculty",        True,  "direct"),
    ("auditorium", "lab_instructor", False, "direct"),  # NOT ALLOWED
    ("auditorium", "hod",            True,  "direct"),
    # sports
    ("sports", "student",        True,  "direct"),
    ("sports", "faculty",        True,  "direct"),
    ("sports", "lab_instructor", True,  "direct"),
    ("sports", "hod",            True,  "direct"),
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
            quota = QUOTA[actor_kind]
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

        # Summary
        for rt in LIMITS:
            count = sum(1 for r in rows if r.resource_type == rt)
            print(f"  {rt}: {count} actor rules")
    finally:
        db.close()


if __name__ == "__main__":
    seed_policies()
