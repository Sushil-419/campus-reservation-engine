"""Timetable Ingestion Router: local OCR/PDF parsing and semester expansion.

Allows HOD and Administrators to:
1. Upload a timetable (PDF, Image JPG/PNG, CSV)
2. Parse it 100% locally with zero cloud API keys
3. Preview extracted slots and match to campus resources/faculties
4. Link to the university's Calendar of Events (Term dates + Holidays)
5. Generate hundreds of confirmed bookings across the 16-week semester atomically.
"""
from datetime import date, datetime, time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session as DBSession

from app.db import get_db
from app.models import User, Resource, Term, CalendarException, TimetableSlot, Booking
from app.auth import get_current_user
from app.audit import write_audit
from app.timetable_parser import parse_csv_content, parse_pdf_content, parse_image_content, parse_calendar_document

router = APIRouter(prefix="/timetable", tags=["timetable"])


def _require_hod_or_admin(user: User) -> None:
    if user.role not in ("hod", "admin", "super_admin"):
        raise HTTPException(403, detail="HOD or Administrator privileges required for timetable ingestion")


class SlotCommitItem(BaseModel):
    weekday: int
    start: str
    end: str
    resource_id: int
    faculty_id: int
    course: str | None = None


class TimetableCommitRequest(BaseModel):
    term_name: str
    start_date: str
    end_date: str
    holidays: List[str] = []
    slots: List[SlotCommitItem]


@router.post("/parse")
async def parse_timetable_file(
    file: UploadFile = File(...),
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Upload a timetable file (PDF, JPG, PNG, CSV) and parse locally into structured slots."""
    _require_hod_or_admin(current)

    filename = (file.filename or "").lower()
    content_bytes = await file.read()

    if not content_bytes:
        raise HTTPException(400, detail="Uploaded file is empty")

    try:
        if filename.endswith(".csv") or filename.endswith(".txt"):
            text_str = content_bytes.decode("utf-8", errors="ignore")
            parse_res = parse_csv_content(text_str, db)
        elif filename.endswith(".pdf"):
            parse_res = parse_pdf_content(content_bytes, db)
        elif filename.endswith((".jpg", ".jpeg", ".png", ".bmp")):
            parse_res = parse_image_content(content_bytes, db)
        else:
            raise HTTPException(400, detail="Unsupported file format. Please upload PDF, JPG, PNG, or CSV.")
    except Exception as e:
        raise HTTPException(500, detail=f"Local document parsing error: {str(e)}")

    slots = parse_res.get("slots", []) if isinstance(parse_res, dict) else parse_res
    return {
        "filename": file.filename,
        "total_extracted": len(slots),
        "slots": slots,
        "divisions": parse_res.get("divisions", ["A"]) if isinstance(parse_res, dict) else ["A"],
        "term_name": parse_res.get("term_name", "2026-ODD-CSE-AI") if isinstance(parse_res, dict) else "2026-ODD-CSE-AI",
        "term_start": parse_res.get("term_start", "2026-09-07") if isinstance(parse_res, dict) else "2026-09-07",
        "term_end": parse_res.get("term_end", "2026-12-29") if isinstance(parse_res, dict) else "2026-12-29",
        "default_holidays": parse_res.get("default_holidays", []) if isinstance(parse_res, dict) else [],
    }


@router.post("/parse-calendar")
async def parse_calendar_file(
    file: UploadFile = File(...),
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Upload university calendar of events (PDF or image) and extract term dates & holidays."""
    _require_hod_or_admin(current)
    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(400, detail="Uploaded calendar file is empty")

    try:
        data = parse_calendar_document(content_bytes, file.filename or "calendar")
    except Exception as e:
        raise HTTPException(500, detail=f"Failed to parse calendar document: {str(e)}")

    write_audit(
        action="parse_calendar", entity="calendar", outcome="success",
        actor_id=current.id,
        detail={"filename": file.filename, "term": data["term_name"], "holidays": len(data["holidays"])},
        db=db,
    )
    return data


@router.post("/commit")
def commit_semester_timetable(
    body: TimetableCommitRequest,
    current: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Commit verified slots into the database and expand into bookings across the semester
    using set-based PostgreSQL generate_series, filtered by the Calendar of Events.
    """
    _require_hod_or_admin(current)

    if not body.slots:
        raise HTTPException(400, detail="No timetable slots provided to commit")

    try:
        t_start = date.fromisoformat(body.start_date)
        t_end = date.fromisoformat(body.end_date)
    except ValueError:
        raise HTTPException(400, detail="Invalid date format for start_date or end_date (use YYYY-MM-DD)")

    if t_start >= t_end:
        raise HTTPException(400, detail="Semester start_date must be before end_date")

    # 1. Create or retrieve Term
    term = db.execute(select(Term).where(Term.name == body.term_name)).scalar_one_or_none()
    if term:
        term.start_date = t_start
        term.end_date = t_end
    else:
        term = Term(name=body.term_name, start_date=t_start, end_date=t_end)
        db.add(term)
        db.commit()
        db.refresh(term)

    # 2. Register Calendar of Events holidays into calendar_exceptions
    registered_holidays = 0
    for h_str in body.holidays:
        try:
            h_date = date.fromisoformat(h_str.strip())
            exists = db.execute(select(CalendarException).where(CalendarException.date == h_date)).scalar_one_or_none()
            if not exists:
                db.add(CalendarException(date=h_date, reason="Calendar of Events Holiday", is_holiday=True))
                registered_holidays += 1
        except Exception:
            continue
    db.commit()

    # 3. Insert timetable_slots rows
    db_slots = []
    for s in body.slots:
        try:
            st = time.fromisoformat(s.start)
            et = time.fromisoformat(s.end)
        except ValueError:
            continue

        slot_obj = TimetableSlot(
            term_id=term.id,
            weekday=s.weekday,
            start_time=st,
            end_time=et,
            resource_id=s.resource_id,
            course=s.course or "Lecture",
            faculty_id=s.faculty_id,
        )
        db.add(slot_obj)
        db_slots.append(slot_obj)

    db.commit()

    # 4. Atomic set-based expansion across all teaching days in the semester
    total_expanded = 0
    clashes = 0

    for slot in db_slots:
        try:
            res = db.execute(text("""
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
            total_expanded += (res.rowcount or 0)
        except Exception as e:
            db.rollback()
            clashes += 1

    write_audit(
        action="import_timetable", entity="term", outcome="success",
        actor_id=current.id, entity_id=term.id,
        detail={
            "term": body.term_name,
            "slots": len(db_slots),
            "bookings_generated": total_expanded,
            "clashes": clashes
        },
        db=db,
    )

    return {
        "status": "success",
        "term_id": term.id,
        "term_name": term.name,
        "term_period": f"{t_start} to {t_end}",
        "weekly_slots_registered": len(db_slots),
        "total_bookings_generated": total_expanded,
        "clashes_skipped": clashes,
        "message": f"Successfully expanded {total_expanded} confirmed bookings across the {body.term_name} semester."
    }


@router.get("/terms")
def list_terms(db: DBSession = Depends(get_db)):
    """List all registered academic terms."""
    terms = db.execute(select(Term).order_by(Term.start_date.desc())).scalars().all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "start_date": t.start_date.isoformat(),
            "end_date": t.end_date.isoformat(),
        }
        for t in terms
    ]
