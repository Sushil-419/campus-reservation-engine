"""Clear all user/booking data from the DB for a clean test slate.

    python scripts/clear_data.py --yes

--yes is REQUIRED: this empties every table in the public schema (users,
resources, reservations, events, series, waitlist, sessions, ...). It never
touches alembic_version, so Alembic still knows which migrations are applied.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402

KEEP = {"alembic_version"}  # migration bookkeeping, never data


def main() -> int:
    if "--yes" not in sys.argv:
        print(__doc__)
        print("Refusing to run without --yes (it deletes ALL data, including users).")
        return 2
    with engine.connect() as conn:
        tables = [
            row[0]
            for row in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
            if row[0] not in KEEP
        ]
        print("Tables found:", tables)
        # Truncate all data tables with cascade to handle FK constraints.
        if tables:
            table_list = ", ".join(tables)
            conn.execute(text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE"))
            conn.commit()
            print(f"Cleared all data from: {table_list} (kept: {', '.join(sorted(KEEP))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
