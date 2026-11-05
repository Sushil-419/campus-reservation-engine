"""Seed demo users.

Run: python -m scripts.seed_users
"""
from app.db import SessionLocal
from app.models import User
from app.auth import hash_password


USERS = []

# Super Admin
USERS.append({
    "email": "superadmin@kletech.ac.in",
    "name": "Super Administrator",
    "password_hash": None,
    "role": "super_admin",
    "department": None,
    "_password": "SuperAdmin@123",
})

# Central Admin
USERS.append({
    "email": "admin@kletech.ac.in",
    "name": "Campus Administrator",
    "password_hash": None,
    "role": "admin",
    "department": None,
    "_password": "Admin@123",
})

# Named Super Admin & Admin
USERS.append({
    "email": "ekbotesushilendr0@gmail.com",
    "name": "Sushilendra Ekbote (Super Admin)",
    "password_hash": None,
    "role": "super_admin",
    "department": "CSE",
    "_password": "Admin@123",
})

USERS.append({
    "email": "vishalkhairamode927@gmail.com",
    "name": "Vishal Khairamode (Admin)",
    "password_hash": None,
    "role": "admin",
    "department": "CSE",
    "_password": "Admin@123",
})

# HODs
USERS.append({
    "email": "hod_cse@kletech.ac.in",
    "name": "Dr. CSE Head (HOD)",
    "password_hash": None,
    "role": "hod",
    "department": "CSE",
    "_password": "Hod@123",
})

USERS.append({
    "email": "hod01@example.edu",
    "name": "HOD Civil",
    "password_hash": None,
    "role": "hod",
    "department": "Civil",
    "_password": "hod123",
})

# Faculty
for i in range(1, 4):
    USERS.append({
        "email": f"faculty{i:02d}@example.edu",
        "name": f"Faculty {i:02d}",
        "password_hash": None,
        "role": "faculty",
        "department": "CSE",
        "_password": "faculty123",
    })

# Lab instructor
USERS.append({
    "email": "lab_instructor01@example.edu",
    "name": "Lab Instructor 01",
    "password_hash": None,
    "role": "lab_instructor",
    "department": "CSE",
    "_password": "instructor123",
})

# CR
USERS.append({
    "email": "cr01@example.edu",
    "name": "CR CSE-A",
    "password_hash": None,
    "role": "cr",
    "department": "CSE",
    "branch": "CSE",
    "division": "A",
    "_password": "cr123",
})

# Students
for i in range(1, 11):
    USERS.append({
        "email": f"student{i:02d}@example.edu",
        "name": f"Student {i:02d}",
        "password_hash": None,
        "role": "student",
        "department": "CSE",
        "_password": "student123",
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
                    existing_user.branch = u.get("branch")
                    existing_user.division = u.get("division")
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
