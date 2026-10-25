"""Add or update Admin (HOD) accounts in the database.

Usage:
    python -m scripts.add_admin
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.db import SessionLocal
from app.models import User
from app.auth import hash_password


ADMINS = [
    {
        "email": "ekbotesushilendr0@gmail.com",
        "name": "Sushilendra Ekbote (Admin)",
        "role": "hod",
        "department": "CSE",
        "password": "Admin@123",
    },
    {
        "email": "vishalkhairamode927@gmail.com",
        "name": "Vishal Khairamode (Admin)",
        "role": "hod",
        "department": "CSE",
        "password": "Admin@123",
    },
]


def add_or_update_admins():
    db = SessionLocal()
    try:
        for admin in ADMINS:
            user = db.query(User).filter(User.email == admin["email"]).first()
            pwd_hash = hash_password(admin["password"])
            if user:
                user.name = admin["name"]
                user.role = admin["role"]
                user.department = admin["department"]
                user.password_hash = pwd_hash
                print(f"Updated existing admin: {admin['email']} (role: {admin['role']})")
            else:
                user = User(
                    email=admin["email"],
                    name=admin["name"],
                    role=admin["role"],
                    department=admin["department"],
                    password_hash=pwd_hash,
                    is_cr=False,
                )
                db.add(user)
                print(f"Created new admin: {admin['email']} (role: {admin['role']})")
        db.commit()
        print("Admin accounts successfully synced to database.")
    except Exception as e:
        db.rollback()
        print(f"Error updating admin accounts: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    add_or_update_admins()
