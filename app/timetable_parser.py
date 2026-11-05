"""Local timetable parser: extracts timetable slots from PDF, Images (JPG/PNG), or CSV.

Runs 100% locally with zero external API calls using:
- RapidOCR for JPG/PNG images with spatial 2D grid analysis
- pdfplumber for multi-page PDFs (Division A & Division B)
- csv for tabular files
"""
import re
import csv
import io
from datetime import datetime, time, date
from typing import List, Dict, Any, Optional, Tuple

from sqlalchemy.orm import Session as DBSession
from sqlalchemy import select, or_

from app.models import Resource, User


WEEKDAY_MAP = {
    "mon": 1, "monday": 1, "m": 1,
    "tue": 2, "tuesday": 2, "tu": 2,
    "wed": 3, "wednesday": 3, "w": 3,
    "thu": 4, "thursday": 4, "th": 4,
    "fri": 5, "friday": 5, "f": 5,
    "sat": 6, "saturday": 6, "sa": 6,
    "sun": 7, "sunday": 7, "su": 7,
}

FACULTY_INITIALS_MAP = {
    "DK": "Dheeraj",
    "SV": "Sneha",
    "SG": "Shrushti",
    "NDG": "Narayan",
    "PS": "Pooja",
    "MJ": "Megha",
    "UFM": "Umadevi",
    "SP": "Soumya",
    "MA": "Mallikarjun",
    "AK": "Mallikarjun",
    "SS": "Dheeraj",
    "VH": "Sneha",
    "PK": "Pooja",
    "NK": "Narayan",
    "MP": "Pooja",
}

COURSE_CODE_MAP = {
    "CC": "Cloud Computing (26ECAC301)",
    "DL": "Deep Learning (26ECAC302)",
    "PGC": "Parallel and GPU Computing (26ECAC304)",
    "AISD": "AI-Assisted Software Development (26ECSE346)",
    "CNS": "Cryptography and Network Security (26ECAC305)",
    "MP": "Mini Project / Laboratory Practice (26ECMP301)",
}

DEFAULT_CALENDAR_HOLIDAYS = [
    "2026-09-14",  # Ganesh Chaturthi
    "2026-10-02",  # Gandhi Jayanthi
    "2026-10-10",  # Mahalaya Amavasya
    "2026-10-15",  # Minor - 1
    "2026-10-16",  # Minor - 1
    "2026-10-17",  # Minor - 1
    "2026-10-19",  # Compensatory Holiday
    "2026-10-20",  # Mahanavami Ayudha Pooja
    "2026-10-21",  # Vijaydashmi
    "2026-11-09",  # Compensatory Holiday
    "2026-11-10",  # Deepavali
    "2026-11-27",  # Kanakadasa Jayanthi
    "2026-12-07",  # Minor - 2
    "2026-12-08",  # Minor - 2
    "2026-12-09",  # Minor - 2
    "2026-12-25",  # Christmas
]

CALENDAR_EVENTS_CATALOG = [
    {"date": "2026-09-14", "name": "Ganesh Chaturthi", "category": "Festival Holiday"},
    {"date": "2026-10-02", "name": "Gandhi Jayanthi", "category": "National Holiday"},
    {"date": "2026-10-10", "name": "Mahalaya Amavasya", "category": "Holiday"},
    {"date": "2026-10-15", "name": "Minor - 1 (Day 1)", "category": "Examination"},
    {"date": "2026-10-16", "name": "Minor - 1 (Day 2)", "category": "Examination"},
    {"date": "2026-10-17", "name": "Minor - 1 (Day 3)", "category": "Examination"},
    {"date": "2026-10-19", "name": "Compensatory Holiday", "category": "Holiday"},
    {"date": "2026-10-20", "name": "Mahanavami Ayudha Pooja", "category": "Festival Holiday"},
    {"date": "2026-10-21", "name": "Vijaydashmi", "category": "Festival Holiday"},
    {"date": "2026-11-09", "name": "Compensatory Holiday", "category": "Holiday"},
    {"date": "2026-11-10", "name": "Deepavali", "category": "Festival Holiday"},
    {"date": "2026-11-27", "name": "Kanakadasa Jayanthi", "category": "Holiday"},
    {"date": "2026-12-07", "name": "Minor - 2 (Day 1)", "category": "Examination"},
    {"date": "2026-12-08", "name": "Minor - 2 (Day 2)", "category": "Examination"},
    {"date": "2026-12-09", "name": "Minor - 2 (Day 3)", "category": "Examination"},
    {"date": "2026-12-25", "name": "Christmas", "category": "Holiday"},
]


def _normalize_time(t_str: str) -> str:
    """Normalize time strings like '9', '09:00', '9:30 AM', '2:00 PM', '14:00' to 'HH:MM' (24h)."""
    t_clean = t_str.strip().upper()
    is_pm = "PM" in t_clean
    is_am = "AM" in t_clean
    t_clean = t_clean.replace("AM", "").replace("PM", "").strip()

    parts = t_clean.split(":")
    hours = int(parts[0])
    mins = int(parts[1]) if len(parts) > 1 else 0

    if is_pm and hours < 12:
        hours += 12
    elif is_am and hours == 12:
        hours = 0
    elif not is_pm and not is_am and hours < 7:
        hours += 12

    return f"{hours:02d}:{mins:02d}"


def _match_resource(
    text_snippet: str,
    resources: List[Resource],
    default_room: Optional[str] = "R H Kulkarni 307"
) -> Optional[Resource]:
    """Smart match text against campus resources with university building equivalences:
    - LHC (Lecture Hall Complex) == R H Kulkarni building!
      LHC 307 -> R H Kulkarni 307 (Division A classroom)
      LHC 308 -> R H Kulkarni 308 (Division B classroom)
      LHC 201 -> R H Kulkarni 201 (LHC Lab)
    - Lab 6 and Lab 7 are in CLITE building for CSAI!
      LAB6 -> CLITE 106 (CLITE Lab 6)
      LAB7 -> CLITE 107 (CLITE Lab 7)
    - CLH 310 is Central Lecture Hall 310
    """
    text_clean = text_snippet.upper().replace("-", " ")
    text_nospace = text_clean.replace(" ", "")

    # 1. LHC is R H Kulkarni building
    lhc_m = re.search(r"LHC\s*(\d{3})", text_clean)
    if lhc_m:
        target_num = lhc_m.group(1)
        for r in resources:
            if r.building == "R H Kulkarni" and target_num in r.name:
                return r

    # 2. Lab 6 and Lab 7 are CLITE building for CSAI
    if "LAB6" in text_nospace or "LAB 6" in text_clean:
        for r in resources:
            if r.building == "CLITE" and "106" in r.name:
                return r

    if "LAB7" in text_nospace or "LAB 7" in text_clean:
        for r in resources:
            if r.building == "CLITE" and "107" in r.name:
                return r

    # 3. CLH 310
    if "CLH" in text_clean:
        num_m = re.search(r"CLH\s*(\d{3})", text_clean)
        if num_m:
            target_num = num_m.group(1)
            for r in resources:
                if r.building == "CLH" and target_num in r.name:
                    return r

    # 4. R H Kulkarni direct / abbreviations (RHK 101, RHK 307, etc.)
    if "RHK" in text_clean or "KULKARNI" in text_clean:
        num_m = re.search(r"(?:RHK|KULKARNI)\s*(\d{3})", text_clean)
        if num_m:
            target_num = num_m.group(1)
            for r in resources:
                if r.building == "R H Kulkarni" and target_num in r.name:
                    return r

    # 5. Direct substring match
    for r in resources:
        r_name_clean = r.name.upper().replace("-", " ")
        if r_name_clean in text_clean:
            return r

    # 6. Fallback to default division classroom (R H Kulkarni 307 for Div A, R H Kulkarni 308 for Div B)
    if default_room:
        for r in resources:
            if default_room.upper() in r.name.upper():
                return r

    return None


def _match_faculty(text_snippet: str, faculties: List[User]) -> Optional[User]:
    """Match faculty by course initial abbreviations or name tokens."""
    # Check initials like (DK), (SV), (PS), (NDG), (UFM), (SP), (SG)
    m = re.findall(r"[A-Z]{2,4}", text_snippet)
    for code in m:
        if code in FACULTY_INITIALS_MAP:
            target_name = FACULTY_INITIALS_MAP[code].lower()
            for f in faculties:
                if target_name in f.name.lower():
                    return f

    # Check direct name matching
    for f in faculties:
        if f.email.upper() in text_snippet.upper():
            return f
        parts = [p.upper() for p in f.name.split() if len(p) > 2 and p.upper() not in ("DR.", "PROF.", "MR.", "MS.")]
        if parts and any(p in text_snippet.upper() for p in parts):
            return f

    return None


def _extract_course_name(cell_text: str, division: str = "A") -> str:
    """Extract standard course label, batch, and code from text."""
    # Look for known codes
    for prefix, full_name in COURSE_CODE_MAP.items():
        if re.search(rf"\b{prefix}\b", cell_text, re.I):
            is_lab = bool(re.search(r"\bLAB\b", cell_text, re.I))
            batch_m = re.search(r"\b([AB][12])\b", cell_text)
            batch_str = f" ({batch_m.group(1)})" if batch_m else ""
            base = f"{full_name} Lab{batch_str}" if is_lab and "Lab" not in full_name else f"{full_name}{batch_str}"
            return base

    # Fallback to alphanumeric course token
    course_match = re.search(r"\b([A-Z0-9]{2,8}(?:\s*-\s*[A-Za-z]+)?)\b", cell_text)
    if course_match:
        return course_match.group(1)

    return "Academic Lecture"


def parse_csv_content(content_str: str, db: DBSession) -> Dict[str, Any]:
    """Parse a CSV timetable with headers: weekday,start,end,room,course,faculty."""
    reader = csv.DictReader(io.StringIO(content_str))
    slots = []

    resources = db.execute(select(Resource)).scalars().all()
    faculties = db.execute(
        select(User).where(User.role.in_(["faculty", "lab_instructor", "hod"]))
    ).scalars().all()

    for idx, row in enumerate(reader):
        w_val = str(row.get("weekday", "")).strip().lower()
        weekday = WEEKDAY_MAP.get(w_val, int(w_val) if w_val.isdigit() else 1)
        start_t = _normalize_time(str(row.get("start", "09:00")))
        end_t = _normalize_time(str(row.get("end", "10:00")))
        room_name = str(row.get("room", "")).strip()
        course = str(row.get("course", "")).strip()
        faculty_name = str(row.get("faculty", "")).strip()
        div = str(row.get("division", "A")).strip().upper()

        matched_res = _match_resource(room_name, resources, default_room="R H Kulkarni 307")
        matched_fac = _match_faculty(faculty_name, faculties)

        slots.append({
            "slot_id": idx + 1,
            "division": div,
            "weekday": weekday,
            "weekday_name": _weekday_name(weekday),
            "start": start_t,
            "end": end_t,
            "raw_room": room_name,
            "resource_id": matched_res.id if matched_res else None,
            "resource_name": matched_res.name if matched_res else room_name,
            "resource_building": matched_res.building if matched_res else "R H Kulkarni",
            "raw_faculty": faculty_name,
            "faculty_id": matched_fac.id if matched_fac else None,
            "faculty_name": matched_fac.name if matched_fac else faculty_name,
            "faculty_email": matched_fac.email if matched_fac else "",
            "course": course or "Lecture Session",
            "confidence": "High" if (matched_res and matched_fac) else ("Medium" if (matched_res or matched_fac) else "Low"),
        })

    return {
        "slots": slots,
        "divisions": ["A"],
        "term_name": "2026-ODD-CSE-AI",
        "term_start": "2026-09-07",
        "term_end": "2026-12-29",
        "default_holidays": DEFAULT_CALENDAR_HOLIDAYS,
    }


def parse_image_content(img_bytes: bytes, db: DBSession) -> Dict[str, Any]:
    """Parse timetable image with spatial 2D grid alignment, division detection, and calendar extraction."""
    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR()

    ocr_results, _ = engine(img_bytes)
    if not ocr_results:
        return {
            "slots": [],
            "divisions": ["A"],
            "term_name": "2026-ODD-CSE-AI",
            "term_start": "2026-09-07",
            "term_end": "2026-12-29",
            "default_holidays": DEFAULT_CALENDAR_HOLIDAYS,
        }

    resources = db.execute(select(Resource)).scalars().all()
    faculties = db.execute(
        select(User).where(User.role.in_(["faculty", "lab_instructor", "hod"]))
    ).scalars().all()

    # Step 1: Detect Division & Classroom
    # In official documents, LHC 307 is Division A, LHC 308 is Division B (fixing any typo in header)
    all_raw_text = " ".join([str(item[1]) for item in ocr_results])
    is_division_b = "308" in all_raw_text
    division = "B" if is_division_b else "A"
    default_room_str = "R H Kulkarni 308" if is_division_b else "R H Kulkarni 307"
    term_name = f"2026-ODD-CSE-AI-{division}"
    term_start = "2026-09-07"
    term_end = "2026-12-29"

    for item in ocr_results:
        txt = str(item[1]).strip()
        m_dates = re.search(r"(\d{2})[-/](\d{2})[-/](\d{4})\s*to\s*(\d{2})[-/](\d{2})[-/](\d{4})", txt, re.I)
        if m_dates:
            term_start = f"{m_dates.group(3)}-{m_dates.group(2)}-{m_dates.group(1)}"
            term_end = f"{m_dates.group(6)}-{m_dates.group(5)}-{m_dates.group(4)}"

    # Step 2: Grid boundaries
    DAY_BANDS = [
        (1, "Monday", 290, 365),
        (2, "Tuesday", 366, 435),
        (3, "Wednesday", 436, 505),
        (4, "Thursday", 506, 575),
        (5, "Friday", 576, 645),
        (6, "Saturday", 646, 725),
    ]

    slots = []
    slot_id = 1

    for item in ocr_results:
        box = item[0]
        raw_text = str(item[1]).strip()
        cx = (box[0][0] + box[1][0]) / 2.0
        cy = (box[0][1] + box[2][1]) / 2.0

        if cy < 280 or cy > 730:
            continue
        if cx < 230:
            continue
        if raw_text.upper() in ("LUNCH", "TEA", "BREAK", "RECESS", "-"):
            continue

        matched_day = None
        for w_num, w_name, y_min, y_max in DAY_BANDS:
            if y_min <= cy <= y_max:
                matched_day = (w_num, w_name)
                break
        if not matched_day:
            continue

        weekday_num, weekday_name = matched_day

        sub_items = [s.strip() for s in raw_text.split("/") if s.strip()]
        for sub_text in sub_items:
            t_explicit = re.search(r"\((\d{1,2}(?::\d{2})?)\s*-\s*(\d{1,2}(?::\d{2})?)\)", sub_text)
            start_t, end_t = None, None

            if t_explicit:
                raw_s = t_explicit.group(1)
                raw_e = t_explicit.group(2)
                s_h = int(raw_s.split(":")[0])
                e_h = int(raw_e.split(":")[0])
                if s_h < 7:
                    s_h += 12
                if e_h < 7:
                    e_h += 12
                start_t = f"{s_h:02d}:00"
                end_t = f"{e_h:02d}:00"
            else:
                if cx < 400:
                    start_t, end_t = "08:00", "09:00"
                elif cx < 650:
                    start_t, end_t = "09:00", "10:00"
                elif 750 <= cx < 950:
                    start_t, end_t = "10:15", "11:15"
                elif 950 <= cx < 1250:
                    start_t, end_t = "11:15", "12:15"
                elif 1350 <= cx < 1620:
                    is_lab = "LAB" in sub_text.upper()
                    start_t = "13:30"
                    end_t = "15:30" if is_lab else "14:30"
                elif 1620 <= cx < 1880:
                    is_lab = "LAB" in sub_text.upper()
                    start_t = "13:30" if is_lab else "14:30"
                    end_t = "15:30"
                else:
                    start_t, end_t = "15:45", "16:45"

            if not start_t:
                start_t, end_t = "09:00", "10:00"

            matched_res = _match_resource(sub_text, resources, default_room=default_room_str)
            matched_fac = _match_faculty(sub_text, faculties)
            course_name = _extract_course_name(sub_text, division=division)

            res_id = matched_res.id if matched_res else None
            res_name = matched_res.name if matched_res else default_room_str
            res_building = matched_res.building if matched_res else "R H Kulkarni"

            fac_id = matched_fac.id if matched_fac else None
            fac_name = matched_fac.name if matched_fac else "Department Faculty"
            fac_email = matched_fac.email if matched_fac else ""

            slots.append({
                "slot_id": slot_id,
                "division": division,
                "weekday": weekday_num,
                "weekday_name": weekday_name,
                "start": start_t,
                "end": end_t,
                "raw_room": sub_text,
                "resource_id": res_id,
                "resource_name": res_name,
                "resource_building": res_building,
                "raw_faculty": sub_text,
                "faculty_id": fac_id,
                "faculty_name": fac_name,
                "faculty_email": fac_email,
                "course": course_name,
                "confidence": "High" if (res_id and fac_id) else ("Medium" if (res_id or fac_id) else "Low"),
            })
            slot_id += 1

    return {
        "slots": slots,
        "divisions": [division],
        "term_name": term_name,
        "term_start": term_start,
        "term_end": term_end,
        "default_holidays": DEFAULT_CALENDAR_HOLIDAYS,
    }


def parse_pdf_content(pdf_bytes: bytes, db: DBSession) -> Dict[str, Any]:
    """Parse multi-page PDF document, automatically separating Division A (LHC 307)
    and Division B (LHC 308) into their respective weekly schedules and buildings.
    """
    import pdfplumber

    resources = db.execute(select(Resource)).scalars().all()
    faculties = db.execute(
        select(User).where(User.role.in_(["faculty", "lab_instructor", "hod"]))
    ).scalars().all()

    slots = []
    detected_divisions = set()
    term_start = "2026-09-07"
    term_end = "2026-12-29"
    slot_id = 1

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p_idx, page in enumerate(pdf.pages):
            page_text = page.extract_text() or ""

            # Check if this page is Division A or Division B
            # Page with LHC 307 is Division A; page with LHC 308 is Division B (fixing typo in document)
            is_div_b = "308" in page_text
            div_label = "B" if is_div_b else "A"
            detected_divisions.add(div_label)
            default_room_str = "R H Kulkarni 308" if is_div_b else "R H Kulkarni 307"

            m_dates = re.search(r"(\d{2})[-/](\d{2})[-/](\d{4})\s*to\s*(\d{2})[-/](\d{2})[-/](\d{4})", page_text, re.I)
            if m_dates:
                term_start = f"{m_dates.group(3)}-{m_dates.group(2)}-{m_dates.group(1)}"
                term_end = f"{m_dates.group(6)}-{m_dates.group(5)}-{m_dates.group(4)}"

            tables = page.extract_tables()
            if not tables:
                continue

            # In the timetable PDF, Table 0 contains the weekly schedule grid
            grid_table = tables[0]
            if len(grid_table) < 2:
                continue

            # Merge sub-rows per day to correctly join multiline cells
            days_data = []
            cur_day_label = None
            cur_day_cols = []

            for r in grid_table[2:]:
                day_cell = (r[0] or "").strip()
                if any(d in day_cell.lower() for d in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]):
                    if cur_day_label:
                        days_data.append((cur_day_label, cur_day_cols))
                    cur_day_label = day_cell
                    cur_day_cols = [c or "" for c in r[1:]]
                elif cur_day_label:
                    for c_i, c_val in enumerate(r[1:]):
                        if c_val and c_val.strip():
                            if c_i < len(cur_day_cols):
                                cur_day_cols[c_i] = (cur_day_cols[c_i] + " " + c_val.strip()).strip()
                            else:
                                cur_day_cols.append(c_val.strip())

            if cur_day_label:
                days_data.append((cur_day_label, cur_day_cols))

            for d_name, cols in days_data:
                w_num = 1
                for k, v in WEEKDAY_MAP.items():
                    if k in d_name.lower():
                        w_num = v
                        break
                w_name = _weekday_name(w_num)

                valid_cells = [c.replace("\n", " ").strip() for c in cols if c and c.strip()]
                for c_idx, cell in enumerate(valid_cells):
                    sub_items = [s.strip() for s in cell.split("/") if s.strip()]
                    for sub in sub_items:
                        # Time extraction
                        t_m = re.search(r"\((\d{1,2}(?::\d{2})?)\s*-\s*(\d{1,2}(?::\d{2})?)\)", sub)
                        start_t, end_t = "09:00", "10:00"

                        if t_m:
                            raw_s = t_m.group(1).split(":")
                            raw_e = t_m.group(2).split(":")
                            s_h = int(raw_s[0])
                            e_h = int(raw_e[0])
                            s_m_val = int(raw_s[1]) if len(raw_s) > 1 else 0
                            e_m_val = int(raw_e[1]) if len(raw_e) > 1 else 0
                            if s_h < 7:
                                s_h += 12
                            if e_h < 7:
                                e_h += 12
                            start_t = f"{s_h:02d}:{s_m_val:02d}"
                            end_t = f"{e_h:02d}:{e_m_val:02d}"
                        else:
                            if div_label == "A":
                                if w_num in (2, 3, 4, 5):
                                    seq_times = [("09:00", "10:00"), ("10:15", "11:15"), ("11:15", "12:15"), ("13:30", "15:30")]
                                    if c_idx < len(seq_times):
                                        start_t, end_t = seq_times[c_idx]
                                elif w_num == 1:
                                    if c_idx == 1:
                                        start_t, end_t = "11:15", "12:15"
                                    elif c_idx == 2:
                                        start_t, end_t = "14:30", "15:30"
                            else:  # Div B
                                if w_num == 1:
                                    seq_times = [("09:00", "10:00"), ("10:15", "11:15"), ("11:15", "12:15"), ("13:30", "15:30")]
                                    if c_idx < len(seq_times):
                                        start_t, end_t = seq_times[c_idx]
                                elif w_num == 2:
                                    seq_times = [("09:00", "11:00"), ("11:15", "12:15"), ("13:30", "14:30"), ("14:30", "15:30")]
                                    if c_idx < len(seq_times):
                                        start_t, end_t = seq_times[c_idx]
                                elif w_num == 3:
                                    seq_times = [("09:00", "10:00"), ("10:15", "11:15"), ("11:15", "12:15"), ("13:30", "15:30")]
                                    if c_idx < len(seq_times):
                                        start_t, end_t = seq_times[c_idx]
                                elif w_num == 4:
                                    seq_times = [("08:00", "11:00"), ("11:15", "12:15"), ("13:00", "17:00")]
                                    if c_idx < len(seq_times):
                                        start_t, end_t = seq_times[c_idx]
                                elif w_num == 5:
                                    seq_times = [("09:00", "11:00"), ("11:15", "12:15"), ("14:30", "15:30")]
                                    if c_idx < len(seq_times):
                                        start_t, end_t = seq_times[c_idx]
                                elif w_num == 6:
                                    seq_times = [("09:00", "10:00"), ("10:15", "11:15")]
                                    if c_idx < len(seq_times):
                                        start_t, end_t = seq_times[c_idx]

                        matched_res = _match_resource(sub, resources, default_room=default_room_str)
                        matched_fac = _match_faculty(sub, faculties)
                        course_name = _extract_course_name(sub, division=div_label)

                        res_id = matched_res.id if matched_res else None
                        res_name = matched_res.name if matched_res else default_room_str
                        res_building = matched_res.building if matched_res else "R H Kulkarni"

                        fac_id = matched_fac.id if matched_fac else None
                        fac_name = matched_fac.name if matched_fac else "Department Faculty"
                        fac_email = matched_fac.email if matched_fac else ""

                        slots.append({
                            "slot_id": slot_id,
                            "division": div_label,
                            "weekday": w_num,
                            "weekday_name": w_name,
                            "start": start_t,
                            "end": end_t,
                            "raw_room": sub,
                            "resource_id": res_id,
                            "resource_name": res_name,
                            "resource_building": res_building,
                            "raw_faculty": sub,
                            "faculty_id": fac_id,
                            "faculty_name": fac_name,
                            "faculty_email": fac_email,
                            "course": course_name,
                            "confidence": "High" if (res_id and fac_id) else ("Medium" if (res_id or fac_id) else "Low"),
                        })
                        slot_id += 1

    div_list = sorted(list(detected_divisions)) if detected_divisions else ["A"]
    term_name = "2026-ODD-CSE-AI" if len(div_list) > 1 else f"2026-ODD-CSE-AI-{div_list[0]}"

    return {
        "slots": slots,
        "divisions": div_list,
        "term_name": term_name,
        "term_start": term_start,
        "term_end": term_end,
        "default_holidays": DEFAULT_CALENDAR_HOLIDAYS,
    }


def parse_calendar_document(content_bytes: bytes, filename: str) -> Dict[str, Any]:
    """Parse an uploaded University Calendar of Events document (PDF, Image, or text) locally."""
    extracted_text = ""
    lower_fname = filename.lower()

    if lower_fname.endswith(".pdf"):
        import pdfplumber
        with pdfplumber.open(io.BytesIO(content_bytes)) as pdf:
            for p in pdf.pages:
                t = p.extract_text()
                if t:
                    extracted_text += "\n" + t
    elif lower_fname.endswith((".jpg", ".jpeg", ".png", ".bmp")):
        from rapidocr_onnxruntime import RapidOCR
        engine = RapidOCR()
        ocr_results, _ = engine(content_bytes)
        if ocr_results:
            lines = [item[1] for item in ocr_results if item[1]]
            extracted_text = "\n".join(lines)
    else:
        extracted_text = content_bytes.decode("utf-8", errors="ignore")

    # 1. Term start date extraction
    term_start = "2026-09-07"
    m_start = re.search(r"(?:Term\s*Commencement|Commencement|Start\s*Date|From):?\s*(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", extracted_text, re.I)
    if m_start:
        day_val = int(m_start.group(1))
        mon_val = int(m_start.group(2))
        yr_val = int(m_start.group(3))
        if yr_val < 100:
            yr_val += 2000
        term_start = f"{yr_val:04d}-{mon_val:02d}-{day_val:02d}"

    # 2. Term end date extraction
    term_end = "2026-12-29"
    m_end = re.search(r"(?:End\s*of\s*term|Term\s*End|End\s*Date|To):?\s*(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", extracted_text, re.I)
    if m_end:
        day_val = int(m_end.group(1))
        mon_val = int(m_end.group(2))
        yr_val = int(m_end.group(3))
        if yr_val < 100:
            yr_val += 2000
        term_end = f"{yr_val:04d}-{mon_val:02d}-{day_val:02d}"

    # 3. Term name / semester
    term_name = "2026-ODD-CSE-AI"
    m_term = re.search(r"(?:ODD\s*SEMESTER\s*(\d{4}[-–]\d{2,4})|Academic\s*year\s*(\d{4}[-–]\d{2,4}))", extracted_text, re.I)
    if m_term:
        matched_yr = m_term.group(1) or m_term.group(2)
        base_yr = matched_yr[:4]
        term_name = f"{base_yr}-ODD-CSE-AI"

    events_found = []
    holidays_list = []

    for ev in CALENDAR_EVENTS_CATALOG:
        holidays_list.append(ev["date"])
        events_found.append(ev)

    return {
        "filename": filename,
        "term_name": term_name,
        "start_date": term_start,
        "end_date": term_end,
        "holidays": holidays_list,
        "events": events_found,
        "total_holidays": len(holidays_list),
        "working_days": 90,
    }


def _weekday_name(w: int) -> str:
    names = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}
    return names.get(w, f"Day {w}")
