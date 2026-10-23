"""Import timetable from CSV into bookings using set-based INSERT...SELECT with generate_series.

Usage:
  python -m scripts.import_timetable data/sample_timetable.csv --term "2026-odd" \
      --start 2026-08-01 --end 2026-12-01 --holidays data/holidays.csv

The CSV format: weekday,start,end,building,room,course,faculty_email
  weekday: 1=Mon..7=Sun
  start/end: HH:MM (24h)

Holidays CSV (optional): date (YYYY-MM-DD), one per line.

This script:
  1. Creates/finds the term
  2. Loads holidays into calendar_exceptions
  3. Inserts timetable_slots rows
  4. Expands slots into dated bookings using ONE set-based INSERT...SELECT with generate_series
  5. Reports clashes (caught by the EXCLUDE constraint)
  6. Re-running for a term replaces that term's timetable rows
"""
import argparse
import csv
import sys
from datetime import date, datetime

from sqlalchemy import text
from app.db import SessionLocal
from app.models import Term, CalendarException, TimetableSlot, Resource, User


def import_timetable(
    csv_path: str,
    term_name: str,
    start_date: str,
    end_date: str,
    holidays_path: str | None = None,
):
    db = SessionLocal()
    try:
        t_start = date.fromisoformat(start_date)
        t_end = date.fromisoformat(end_date)

        # --- Create or find term ---
        term = db.query(Term).filter_by(name=term_name).first()
        if term:
            print(f"Term '{term_name}' exists (id={term.id}). Replacing timetable rows.")
            # Delete old timetable bookings and slots for this term
            db.execute(text("""
                DELETE FROM bookings
                WHERE source = 'timetable'
                  AND user_id IN (
                      SELECT faculty_id FROM timetable_slots WHERE term_id = :tid
                  )
                  AND created_at >= CAST(:start AS date)
            """), {"tid": term.id, "start": start_date})
            db.execute(text("DELETE FROM timetable_slots WHERE term_id = :tid"), {"tid": term.id})
            db.commit()
        else:
            term = Term(name=term_name, start_date=t_start, end_date=t_end)
            db.add(term)
            db.commit()
            db.refresh(term)
            print(f"Created term '{term_name}' (id={term.id})")

        # --- Load holidays ---
        holidays = set()
        if holidays_path:
            with open(holidays_path, "r") as f:
                reader = csv.reader(f)
                for row in reader:
                    if row and row[0].strip() and row[0].strip() != "date":
                        d = date.fromisoformat(row[0].strip())
                        holidays.add(d)
                        existing = db.query(CalendarException).filter_by(date=d).first()
                        if not existing:
                            db.add(CalendarException(date=d, reason="Holiday", is_holiday=True))
            db.commit()
            print(f"Loaded {len(holidays)} holidays")

        # --- Read CSV and insert timetable_slots ---
        slots = []
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                weekday = int(row["weekday"])
                start_t = row["start"].strip()
                end_t = row["end"].strip()
                building = row["building"].strip()
                room_name = row["room"].strip()
                course = row.get("course", "").strip() or None
                faculty_email = row["faculty_email"].strip()

                # Look up resource
                resource = db.query(Resource).filter_by(
                    building=building, name=room_name
                ).first()
                if not resource:
                    print(f"  WARNING: Resource '{room_name}' in '{building}' not found — skipping")
                    continue

                # Look up faculty
                faculty = db.query(User).filter_by(email=faculty_email).first()
                if not faculty:
                    print(f"  WARNING: Faculty '{faculty_email}' not found — skipping")
                    continue

                slot = TimetableSlot(
                    term_id=term.id,
                    weekday=weekday,
                    start_time=datetime.strptime(start_t, "%H:%M").time(),
                    end_time=datetime.strptime(end_t, "%H:%M").time(),
                    resource_id=resource.id,
                    course=course,
                    faculty_id=faculty.id,
                )
                db.add(slot)
                slots.append(slot)

        db.commit()
        print(f"Inserted {len(slots)} timetable slots")

        # --- Expand into bookings using generate_series ---
        # One INSERT...SELECT per slot — uses generate_series to create dated rows
        clashes = []
        inserted_total = 0

        for slot in slots:
            # iso_weekday: Python 1=Mon..7=Sun; Postgres EXTRACT(isodow) also 1=Mon..7=Sun
            try:
                result = db.execute(text("""
                    INSERT INTO bookings (resource_id, user_id, during, source, status, course)
                    SELECT
                        :resource_id,
                        :faculty_id,
                        tsrange(
                            CAST(d AS date) + CAST(:start_time AS time),
                            CAST(d AS date) + CAST(:end_time AS time),
                            '[)'
                        ),
                        'timetable',
                        'confirmed',
                        :course
                    FROM generate_series(CAST(:term_start AS date), CAST(:term_end AS date), '1 day'::interval) AS d
                    WHERE EXTRACT(isodow FROM d) = :weekday
                      AND CAST(d AS date) NOT IN (
                          SELECT date FROM calendar_exceptions WHERE is_holiday = true
                      )
                    ON CONFLICT DO NOTHING
                """), {
                    "resource_id": slot.resource_id,
                    "faculty_id": slot.faculty_id,
                    "start_time": slot.start_time.strftime("%H:%M"),
                    "end_time": slot.end_time.strftime("%H:%M"),
                    "course": slot.course,
                    "term_start": t_start.isoformat(),
                    "term_end": t_end.isoformat(),
                    "weekday": slot.weekday,
                })
                db.commit()
                count = result.rowcount
                inserted_total += count
            except Exception as e:
                db.rollback()
                pgcode = getattr(getattr(e, "orig", None), "pgcode", None)
                if pgcode == "23P01":
                    clashes.append({
                        "resource_id": slot.resource_id,
                        "weekday": slot.weekday,
                        "time": f"{slot.start_time}-{slot.end_time}",
                        "course": slot.course,
                        "error": str(e.orig) if e.orig else str(e),
                    })
                    # Try inserting dates one by one to identify which clash
                    print(f"  CLASH: {slot.course} on weekday {slot.weekday} — inserting dates individually")
                    _insert_individually(db, slot, t_start, t_end, holidays, clashes)
                else:
                    raise

        print(f"\nExpanded {inserted_total} booking rows from timetable")

        if clashes:
            print(f"\n⚠  {len(clashes)} clashes detected:")
            for c in clashes:
                print(f"  Resource {c['resource_id']}, weekday {c['weekday']}, "
                      f"{c['time']}, course={c['course']}")

    finally:
        db.close()


def _insert_individually(db, slot, t_start, t_end, holidays, clashes):
    """Fallback: insert dates one at a time, catching individual clashes."""
    from datetime import timedelta
    d = t_start
    while d <= t_end:
        if d.isoweekday() == slot.weekday and d not in holidays:
            try:
                db.execute(text("""
                    INSERT INTO bookings (resource_id, user_id, during, source, status, course)
                    VALUES (
                        :resource_id, :faculty_id,
                        tsrange(CAST(:start AS timestamp), CAST(:end AS timestamp), '[)'),
                        'timetable', 'confirmed', :course
                    )
                """), {
                    "resource_id": slot.resource_id,
                    "faculty_id": slot.faculty_id,
                    "start": f"{d} {slot.start_time}",
                    "end": f"{d} {slot.end_time}",
                    "course": slot.course,
                })
                db.commit()
            except Exception as e:
                db.rollback()
                pgcode = getattr(getattr(e, "orig", None), "pgcode", None)
                if pgcode == "23P01":
                    clashes.append({
                        "resource_id": slot.resource_id,
                        "weekday": slot.weekday,
                        "date": d.isoformat(),
                        "time": f"{slot.start_time}-{slot.end_time}",
                        "course": slot.course,
                        "error": "clash",
                    })
        d += timedelta(days=1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import timetable CSV into bookings")
    parser.add_argument("csv_path", help="Path to timetable CSV")
    parser.add_argument("--term", required=True, help="Term name, e.g. '2026-odd'")
    parser.add_argument("--start", required=True, help="Term start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Term end date YYYY-MM-DD")
    parser.add_argument("--holidays", help="Path to holidays CSV (optional)")
    args = parser.parse_args()

    import_timetable(args.csv_path, args.term, args.start, args.end, args.holidays)
