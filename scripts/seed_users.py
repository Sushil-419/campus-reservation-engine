"""Seed demo users.

Run: python -m scripts.seed_users
"""
from app.db import SessionLocal
from app.models import User
from app.auth import hash_password


USERS = []

# 20 students
for i in range(1, 21):
    USERS.append({
        "email": f"student{i:02d}@example.edu",
        "name": f"Student {i:02d}",
        "password_hash": None,  # filled below
        "role": "student",
        "is_cr": False,
        "department": None,
        "_password": "student123",
    })

# 1 CR
USERS.append({
    "email": "cr01@example.edu",
    "name": "CR 01",
    "password_hash": None,
    "role": "student",
    "is_cr": True,
    "department": None,
    "_password": "cr123",
})

# 3 faculty
for i in range(1, 4):
    USERS.append({
        "email": f"faculty{i:02d}@example.edu",
        "name": f"Faculty {i:02d}",
        "password_hash": None,
        "role": "faculty",
        "is_cr": False,
        "department": None,
        "_password": "faculty123",
    })

# 1 lab instructor
USERS.append({
    "email": "lab_instructor01@example.edu",
    "name": "Lab Instructor 01",
    "password_hash": None,
    "role": "lab_instructor",
    "is_cr": False,
    "department": None,
    "_password": "instructor123",
})

# 1 HOD
USERS.append({
    "email": "hod01@example.edu",
    "name": "HOD 01",
    "password_hash": None,
    "role": "hod",
    "is_cr": False,
    "department": "Civil",
    "_password": "hod123",
})


def seed_users():
    db = SessionLocal()
    try:
        existing = db.query(User).count()
        if existing > 0:
            print(f"Users table already has {existing} rows — skipping.")
            return

        objs = []
        for u in USERS:
            pwd = u.pop("_password")
            u["password_hash"] = hash_password(pwd)
            objs.append(User(**u))

        db.add_all(objs)
        db.commit()
        print(f"Seeded {len(objs)} users.")

        # Summary
        from collections import Counter
        by_role = Counter((u.role, u.is_cr) for u in objs)
        for (role, is_cr), count in sorted(by_role.items()):
            label = f"{role}" + (" (CR)" if is_cr else "")
            print(f"  {label}: {count}")
    finally:
        db.close()


if __name__ == "__main__":
    seed_users()
