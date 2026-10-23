"""Populate the dev database with realistic demo resources.

Safe to re-run any time: it clears every row from reservations, users,
and resources first, then reseeds a fixed set of resources. Users are no
longer seeded here — real accounts only ever come from /auth/signup or
Google OAuth login now, so sign up (or log in with Google) after running
this to get a real account, then use the app normally.

Run with:
    venv\\Scripts\\python.exe scripts\\seed.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Resource  # noqa: E402


def clear_tables(db):
    db.execute(text("TRUNCATE reservations, users, resources RESTART IDENTITY CASCADE"))
    db.commit()


def seed_resources(db):
    resources = [
        Resource(name="Conference Room A", type="room", capacity=8),
        Resource(name="Conference Room B (Exec)", type="room", capacity=4),
        Resource(name="3D Printer", type="equipment", capacity=1),
        Resource(name="Projector Cart", type="equipment", capacity=1),
        Resource(name="Sports Hall", type="facility", capacity=20),
    ]
    db.add_all(resources)
    db.commit()
    for r in resources:
        db.refresh(r)
    return {r.name: r for r in resources}


def main():
    db = SessionLocal()
    try:
        print("Clearing existing data...")
        clear_tables(db)

        print("Seeding resources...")
        resources = seed_resources(db)
        print(f"  created {len(resources)} resources")

        print("\n=== Seed summary ===")

        print("\nResources:")
        for r in resources.values():
            print(f"  #{r.id}  {r.name:<26} type={r.type:<10} capacity={r.capacity}")

        print(
            "\nNo users seeded. Sign up at /signup.html or sign in with Google "
            "to create a real account. sharan.sp95@gmail.com is auto-approved as "
            "admin; every other account starts pending until approved."
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()
