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

# Admin HODs
USERS.append({
    "email": "ekbotesushilendr0@gmail.com",
    "name": "Sushilendra Ekbote (Admin)",
    "password_hash": None,
    "role": "hod",
    "is_cr": False,
    "department": "CSE",
    "_password": "Admin@123",
})

USERS.append({
    "email": "vishalkhairamode927@gmail.com",
    "name": "Vishal Khairamode (Admin)",
    "password_hash": None,
    "role": "hod",
    "is_cr": False,
    "department": "CSE",
    "_password": "Admin@123",
})


def seed_users():
    db = SessionLocal()
    try:
        created = 0
        updated = 0
        for u in USERS:
            pwd = u.pop("_password", None)
            email = u["email"]
            existing_user = db.query(User).filter(User.email == email).first()
            if existing_user:
                if pwd:
                    existing_user.password_hash = hash_password(pwd)
                    existing_user.role = u["role"]
                    existing_user.name = u["name"]
                    existing_user.department = u.get("department")
                    updated += 1
            else:
                if pwd:
                    u["password_hash"] = hash_password(pwd)
                db.add(User(**u))
                created += 1

        db.commit()
        print(f"Users seed completed: {created} created, {updated} updated.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_users()
