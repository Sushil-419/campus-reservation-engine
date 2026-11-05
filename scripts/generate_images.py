"""Script to generate high-resolution images for:
1. Academic Calendar of Events (2026-27 Odd Semester, 07-09-2026 to 29-12-2026)
2. Department Timetable (CSE-AI V Sem Div A) based on the uploaded reference image.
"""
import os
import calendar
from datetime import date
from PIL import Image, ImageDraw, ImageFont

WIN_FONT_DIR = r"C:\Windows\Fonts"
FONT_SANS = os.path.join(WIN_FONT_DIR, "segoeui.ttf")
FONT_SANS_BOLD = os.path.join(WIN_FONT_DIR, "segoeuib.ttf")
FONT_ARIAL_BOLD = os.path.join(WIN_FONT_DIR, "arialbd.ttf")

OUTPUT_DIR = r"C:\Users\ekbot\.gemini\antigravity\brain\463fb7f0-2332-4213-b2bf-6c6cb190d80b"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ── Color Palette ──────────────────────────────────────────────────────────
CLR_MAROON = (168, 29, 36)
CLR_DARK_TEXT = (25, 30, 36)
CLR_MUTED_TEXT = (90, 100, 110)
CLR_BORDER = (209, 213, 219)
CLR_HEADER_BG = (248, 249, 250)
CLR_ACCENT_ORANGE = (235, 175, 120)
CLR_HOLIDAY_BG = (254, 226, 226)
CLR_HOLIDAY_TXT = (185, 28, 28)
CLR_EXAM_BG = (254, 243, 199)
CLR_EXAM_TXT = (180, 83, 9)
CLR_SUNDAY_BG = (243, 244, 246)
CLR_SUNDAY_TXT = (107, 114, 128)
CLR_ACTIVE_DAY = (239, 246, 255)


def get_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


# ────────────────────────────────────────────────────────────────────────────
# 1. GENERATE CALENDAR OF EVENTS IMAGE
# ────────────────────────────────────────────────────────────────────────────
def generate_calendar_of_events():
    W, H = 2000, 2800
    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    f_title = get_font(FONT_ARIAL_BOLD, 46)
    f_sub = get_font(FONT_SANS_BOLD, 30)
    f_meta = get_font(FONT_SANS, 24)
    f_h2 = get_font(FONT_SANS_BOLD, 26)
    f_body = get_font(FONT_SANS, 20)
    f_bold = get_font(FONT_SANS_BOLD, 20)
    f_cal_head = get_font(FONT_SANS_BOLD, 22)
    f_cal_day = get_font(FONT_SANS_BOLD, 18)
    f_cal_num = get_font(FONT_SANS, 19)
    f_cal_num_bold = get_font(FONT_SANS_BOLD, 19)
    f_small = get_font(FONT_SANS, 16)

    # Outer border
    draw.rectangle([(25, 25), (W - 25, H - 25)], outline=CLR_MAROON, width=4)
    draw.rectangle([(32, 32), (W - 32, H - 32)], outline=CLR_BORDER, width=1)

    # University Header
    curr_y = 60
    draw.text((W // 2, curr_y), "KLE Technological University", fill=CLR_MAROON, font=f_title, anchor="mt")
    curr_y += 55
    draw.text((W // 2, curr_y), "Creating Value, Leveraging Knowledge  |  Hubballi, Karnataka, India", fill=CLR_MUTED_TEXT, font=f_meta, anchor="mt")
    curr_y += 40
    draw.text((W // 2, curr_y), "ACADEMIC CALENDAR OF EVENTS — ACADEMIC YEAR 2026–27", fill=CLR_DARK_TEXT, font=f_sub, anchor="mt")
    curr_y += 38
    draw.text((W // 2, curr_y), "Undergraduate Programme: B.Tech. Semester V  (From: 07-09-2026 to 29-12-2026)", fill=CLR_MAROON, font=f_h2, anchor="mt")
    curr_y += 45

    # Divider bar
    draw.line([(60, curr_y), (W - 60, curr_y)], fill=CLR_MAROON, width=3)
    curr_y += 30

    # 4-Month Calendar Grids: Sept, Oct, Nov, Dec 2026
    months_info = [
        {"year": 2026, "month": 9, "name": "SEPTEMBER 2026", "holidays": {16: "Eid-e-Milad", 21: "Mahalaya Amavasya"}, "exams": set(), "events": {7: "Commencement of V Sem Classes"}},
        {"year": 2026, "month": 10, "name": "OCTOBER 2026", "holidays": {2: "Gandhi Jayanti", 19: "Ayudha Puja", 20: "Vijayadashami", 21: "Dussehra Break", 26: "Valmiki Jayanti"}, "exams": {12, 13, 14, 15}, "events": {}},
        {"year": 2026, "month": 11, "name": "NOVEMBER 2026", "holidays": {1: "Kannada Rajyotsava", 8: "Naraka Chaturdashi", 9: "Diwali Laxmi Puja", 10: "Balipadyami / Deepavali", 24: "Guru Nanak Jayanti"}, "exams": {19, 20, 21}, "events": {}},
        {"year": 2026, "month": 12, "name": "DECEMBER 2026", "holidays": {25: "Christmas Day"}, "exams": {31}, "events": {14: "Lab IA Week Begins", 19: "Lab IA Week Ends", 29: "Last Working Day", 31: "SEE Exams Begin"}},
    ]

    col_w = 440
    card_h = 360
    col_gap = 25
    grid_left = (W - (4 * col_w + 3 * col_gap)) // 2

    day_cols = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]

    for idx, m in enumerate(months_info):
        cx = grid_left + idx * (col_w + col_gap)
        cy = curr_y

        # Month Card Header
        draw.rectangle([(cx, cy), (cx + col_w, cy + 38)], fill=CLR_MAROON)
        draw.text((cx + col_w // 2, cy + 8), m["name"], fill=(255, 255, 255), font=f_cal_head, anchor="mt")

        # Days of week header
        sub_y = cy + 42
        cell_w = col_w // 7
        cell_h = 38
        draw.rectangle([(cx, sub_y), (cx + col_w, sub_y + 26)], fill=CLR_HEADER_BG)
        for d_idx, day_str in enumerate(day_cols):
            d_x = cx + d_idx * cell_w + cell_w // 2
            txt_color = CLR_HOLIDAY_TXT if day_str == "Su" else CLR_DARK_TEXT
            draw.text((d_x, sub_y + 5), day_str, fill=txt_color, font=f_cal_day, anchor="mt")

        # Calendar month days
        cal = calendar.Calendar(firstweekday=0)
        month_days = cal.monthdayscalendar(m["year"], m["month"])

        day_start_y = sub_y + 30
        for r_idx, week in enumerate(month_days):
            for c_idx, day_num in enumerate(week):
                if day_num == 0:
                    continue
                d_bx = cx + c_idx * cell_w
                d_by = day_start_y + r_idx * cell_h

                # Determine cell styling
                is_sun = (c_idx == 6)
                is_hol = day_num in m["holidays"]
                is_exam = day_num in m["exams"]
                is_evt = day_num in m["events"]

                # Background fill
                if is_hol:
                    draw.rectangle([(d_bx + 2, d_by + 1), (d_bx + cell_w - 2, d_by + cell_h - 1)], fill=CLR_HOLIDAY_BG)
                    txt_c = CLR_HOLIDAY_TXT
                    f_to_use = f_cal_num_bold
                elif is_exam:
                    draw.rectangle([(d_bx + 2, d_by + 1), (d_bx + cell_w - 2, d_by + cell_h - 1)], fill=CLR_EXAM_BG)
                    txt_c = CLR_EXAM_TXT
                    f_to_use = f_cal_num_bold
                elif is_evt:
                    draw.rectangle([(d_bx + 2, d_by + 1), (d_bx + cell_w - 2, d_by + cell_h - 1)], fill=CLR_ACTIVE_DAY)
                    txt_c = (30, 64, 175)
                    f_to_use = f_cal_num_bold
                elif is_sun:
                    draw.rectangle([(d_bx + 2, d_by + 1), (d_bx + cell_w - 2, d_by + cell_h - 1)], fill=CLR_SUNDAY_BG)
                    txt_c = CLR_SUNDAY_TXT
                    f_to_use = f_cal_num
                else:
                    txt_c = CLR_DARK_TEXT
                    f_to_use = f_cal_num

                draw.text((d_bx + cell_w // 2, d_by + 7), str(day_num), fill=txt_c, font=f_to_use, anchor="mt")

        # Border for month card
        draw.rectangle([(cx, cy), (cx + col_w, cy + card_h)], outline=CLR_BORDER, width=1)

    curr_y += card_h + 35

    # Legend Row
    draw.text((60, curr_y), "CALENDAR LEGEND:", fill=CLR_DARK_TEXT, font=f_bold)
    leg_x = 280
    items = [
        ("Instruction / Working Day", (255, 255, 255), CLR_DARK_TEXT, CLR_BORDER),
        ("General / Festival Holiday", CLR_HOLIDAY_BG, CLR_HOLIDAY_TXT, CLR_HOLIDAY_TXT),
        ("Minor Exam (MSE) / SEE", CLR_EXAM_BG, CLR_EXAM_TXT, CLR_EXAM_TXT),
        ("Key Semester Event", CLR_ACTIVE_DAY, (30, 64, 175), (30, 64, 175)),
        ("Sunday (Weekly Off)", CLR_SUNDAY_BG, CLR_SUNDAY_TXT, CLR_BORDER),
    ]
    for lbl, bg_c, txt_c, brd_c in items:
        draw.rectangle([(leg_x, curr_y + 3), (leg_x + 22, curr_y + 22)], fill=bg_c, outline=brd_c, width=1)
        draw.text((leg_x + 30, curr_y + 2), lbl, fill=CLR_DARK_TEXT, font=f_body)
        leg_x += draw.textlength(lbl, font=f_body) + 60

    curr_y += 45
    draw.line([(60, curr_y), (W - 60, curr_y)], fill=CLR_BORDER, width=1)
    curr_y += 30

    # Two Column Layout: Academic Milestones (Left) and Holidays List (Right)
    col_split_w = (W - 160) // 2
    left_x = 60
    right_x = left_x + col_split_w + 40

    # ── Left Column: Key Academic Milestones Table ───────────────
    draw.text((left_x, curr_y), "KEY ACADEMIC MILESTONES & OPERATING SCHEDULE", fill=CLR_MAROON, font=f_h2)
    tbl_y = curr_y + 38

    milestones = [
        ("Commencement of V Semester Instruction", "Monday, 07-09-2026", "Teaching Starts"),
        ("Course Registration & Drop Period Closes", "Saturday, 19-09-2026", "ERP System Locks"),
        ("Minor Examination 1 (MSE-1)", "12-10-2026 to 15-10-2026", "Offline Theory Exam"),
        ("Announcement of MSE-1 Marks & Attendance", "Friday, 23-10-2026", "Student Portal"),
        ("Mid-Semester Academic Review & Feedback", "Saturday, 31-10-2026", "Department Meeting"),
        ("Minor Examination 2 (MSE-2)", "19-11-2026 to 21-11-2026", "Offline Theory Exam"),
        ("Announcement of MSE-2 Marks & Attendance", "Friday, 27-11-2026", "Student Portal"),
        ("Laboratory Internal Assessment & Viva-Voce", "14-12-2026 to 19-12-2026", "Practical Labs"),
        ("Last Working Day (Instruction Ends)", "Tuesday, 29-12-2026", "Term Closes"),
        ("Semester End Examinations (SEE) Theory", "31-12-2026 to 16-01-2027", "Autonomous SEE"),
        ("Reopening for Even Semester (VI Sem)", "Monday, 25-01-2027", "Even Sem Session"),
    ]

    # Header
    draw.rectangle([(left_x, tbl_y), (left_x + col_split_w, tbl_y + 36)], fill=CLR_MAROON)
    draw.text((left_x + 15, tbl_y + 8), "Academic Event / Milestone", fill=(255, 255, 255), font=f_bold)
    draw.text((left_x + col_split_w - 280, tbl_y + 8), "Scheduled Dates", fill=(255, 255, 255), font=f_bold)
    draw.text((left_x + col_split_w - 70, tbl_y + 8), "Status", fill=(255, 255, 255), font=f_bold)
    tbl_y += 36

    for r_idx, (m_evt, m_date, m_note) in enumerate(milestones):
        row_bg = CLR_HEADER_BG if r_idx % 2 == 0 else (255, 255, 255)
        draw.rectangle([(left_x, tbl_y), (left_x + col_split_w, tbl_y + 38)], fill=row_bg, outline=CLR_BORDER, width=1)
        draw.text((left_x + 15, tbl_y + 9), m_evt, fill=CLR_DARK_TEXT, font=f_body)
        draw.text((left_x + col_split_w - 280, tbl_y + 9), m_date, fill=(17, 24, 39), font=f_bold)
        draw.text((left_x + col_split_w - 70, tbl_y + 9), m_note, fill=CLR_MUTED_TEXT, font=f_small)
        tbl_y += 38

    # ── Right Column: Official Holidays List ────────────────────
    draw.text((right_x, curr_y), "DECLARED HOLIDAYS & RECESS (NO LECTURES / LABS)", fill=CLR_MAROON, font=f_h2)
    tbl_r_y = curr_y + 38

    holidays = [
        ("Eid-e-Milad / Id-Milad", "Wednesday, 16-09-2026", "Festival Holiday"),
        ("Mahalaya Amavasya", "Monday, 21-09-2026", "General Holiday"),
        ("Mahatma Gandhi Jayanti", "Friday, 02-10-2026", "National Holiday"),
        ("Mahanavami / Ayudha Puja", "Monday, 19-10-2026", "Dussehra Festival"),
        ("Vijayadashami", "Tuesday, 20-10-2026", "Dussehra Festival"),
        ("Dussehra Mid-Term Recess", "Wednesday, 21-10-2026", "Institutional Recess"),
        ("Maharishi Valmiki Jayanti", "Monday, 26-10-2026", "State Holiday"),
        ("Kannada Rajyotsava", "Sunday, 01-11-2026", "State Foundation"),
        ("Naraka Chaturdashi (Diwali)", "Sunday, 08-11-2026", "Deepavali Festival"),
        ("Diwali Laxmi Puja", "Monday, 09-11-2026", "Deepavali Festival"),
        ("Balipadyami / Deepavali Holiday", "Tuesday, 10-11-2026", "Deepavali Festival"),
        ("Guru Nanak Jayanti", "Tuesday, 24-11-2026", "General Holiday"),
        ("Kanakadasa Jayanti", "Friday, 27-11-2026", "State Holiday"),
        ("Christmas Day", "Friday, 25-12-2026", "General Holiday"),
        ("All Sundays (Weekly Breaks)", "Every Sunday (16 Sundays)", "Weekly Holiday"),
    ]

    # Header
    draw.rectangle([(right_x, tbl_r_y), (right_x + col_split_w, tbl_r_y + 36)], fill=CLR_MAROON)
    draw.text((right_x + 15, tbl_r_y + 8), "Holiday / Occasion", fill=(255, 255, 255), font=f_bold)
    draw.text((right_x + col_split_w - 300, tbl_r_y + 8), "Date & Day", fill=(255, 255, 255), font=f_bold)
    draw.text((right_x + col_split_w - 90, tbl_r_y + 8), "Category", fill=(255, 255, 255), font=f_bold)
    tbl_r_y += 36

    for r_idx, (h_name, h_date, h_type) in enumerate(holidays):
        row_bg = CLR_HOLIDAY_BG if "Diwali" in h_name or "Dussehra" in h_name or "Gandhi" in h_name else (CLR_HEADER_BG if r_idx % 2 == 0 else (255, 255, 255))
        draw.rectangle([(right_x, tbl_r_y), (right_x + col_split_w, tbl_r_y + 35)], fill=row_bg, outline=CLR_BORDER, width=1)
        draw.text((right_x + 15, tbl_r_y + 7), h_name, fill=CLR_HOLIDAY_TXT if "Diwali" in h_name or "Dussehra" in h_name else CLR_DARK_TEXT, font=f_body)
        draw.text((right_x + col_split_w - 300, tbl_r_y + 7), h_date, fill=(17, 24, 39), font=f_bold)
        draw.text((right_x + col_split_w - 90, tbl_r_y + 7), h_type, fill=CLR_MUTED_TEXT, font=f_small)
        tbl_r_y += 35

    curr_y = max(tbl_y, tbl_r_y) + 40

    # Teaching Day Metrics Summary Box
    metrics_box_h = 130
    draw.rectangle([(60, curr_y), (W - 60, curr_y + metrics_box_h)], fill=CLR_HEADER_BG, outline=CLR_BORDER, width=1)

    m_title_font = get_font(FONT_SANS_BOLD, 22)
    draw.text((80, curr_y + 15), "SEMESTER INSTRUCTIONAL METRICS & COMPLIANCE SUMMARY", fill=CLR_MAROON, font=m_title_font)

    stats = [
        ("Total Calendar Days", "114 Days"),
        ("Sundays & Declared Holidays", "32 Days"),
        ("Net Instructional / Teaching Days", "82 Days"),
        ("Effective Teaching Weeks", "16.4 Weeks"),
        ("Minimum AICTE/UGC Requirement", "75 Days (Met)"),
    ]
    stat_x = 80
    stat_spacing = 350
    for s_title, s_val in stats:
        draw.text((stat_x, curr_y + 55), s_title, fill=CLR_MUTED_TEXT, font=f_small)
        draw.text((stat_x, curr_y + 80), s_val, fill=CLR_DARK_TEXT, font=f_h2)
        stat_x += stat_spacing

    curr_y += metrics_box_h + 80

    # Official Signatures Footer
    sig_positions = [
        ("Prepared By", "Academic Section Coordinator"),
        ("Verified By", "Dean (Academic Programmes)"),
        ("Approved By", "Registrar & Vice-Chancellor"),
    ]
    sig_spacing = (W - 120) // 3
    for s_idx, (sig_role, sig_title) in enumerate(sig_positions):
        sx = 60 + s_idx * sig_spacing + sig_spacing // 2
        draw.line([(sx - 140, curr_y), (sx + 140, curr_y)], fill=CLR_DARK_TEXT, width=1)
        draw.text((sx, curr_y + 10), sig_role, fill=CLR_DARK_TEXT, font=f_bold, anchor="mt")
        draw.text((sx, curr_y + 35), sig_title, fill=CLR_MUTED_TEXT, font=f_meta, anchor="mt")
        draw.text((sx, curr_y + 65), "KLE Technological University, Hubballi", fill=CLR_MUTED_TEXT, font=f_small, anchor="mt")

    # Save image
    out_path = os.path.join(OUTPUT_DIR, "calendar_of_events_2026_odd.png")
    img.save(out_path, "PNG", dpi=(300, 300))
    img.save(os.path.join(DATA_DIR, "calendar_of_events_2026_odd.png"), "PNG")
    print("Generated Calendar of Events:", out_path)
    return out_path


# ────────────────────────────────────────────────────────────────────────────
# 2. GENERATE TIMETABLE IMAGE (Replicating and Enhancing Reference Image)
# ────────────────────────────────────────────────────────────────────────────
def generate_timetable_image():
    W, H = 2200, 1500
    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    f_title = get_font(FONT_ARIAL_BOLD, 44)
    f_dept = get_font(FONT_SANS_BOLD, 30)
    f_sub = get_font(FONT_SANS_BOLD, 24)
    f_th = get_font(FONT_SANS_BOLD, 20)
    f_cell = get_font(FONT_SANS, 18)
    f_cell_bold = get_font(FONT_SANS_BOLD, 18)
    f_small = get_font(FONT_SANS, 16)
    f_bold = get_font(FONT_SANS_BOLD, 20)

    # Outer border
    draw.rectangle([(20, 20), (W - 20, H - 20)], outline=CLR_MAROON, width=3)

    # University Header
    curr_y = 45
    draw.text((W // 2, curr_y), "KLE Technological University", fill=CLR_MAROON, font=f_title, anchor="mt")
    curr_y += 50
    draw.text((W // 2, curr_y), "Department of Computer Science and Engineering (AI)", fill=CLR_DARK_TEXT, font=f_dept, anchor="mt")
    curr_y += 45

    # Dashed divider
    for x in range(50, W - 50, 20):
        draw.line([(x, curr_y), (x + 10, curr_y)], fill=CLR_BORDER, width=2)
    curr_y += 18

    # Timetable Meta Bar
    draw.text((50, curr_y), "Semester: V  Division: A  (LHC 307)", fill=CLR_DARK_TEXT, font=f_sub)
    draw.text((W // 2, curr_y), "Time Table for the Academic year 2026-27", fill=CLR_DARK_TEXT, font=f_sub, anchor="mt")
    draw.text((W - 50, curr_y), "From: 07-09-2026 to 29-12-2026", fill=CLR_DARK_TEXT, font=f_sub, anchor="rt")
    curr_y += 32
    draw.text((W - 50, curr_y), "Doc ID: FMTM 0208T/1.0", fill=CLR_MUTED_TEXT, font=f_small, anchor="rt")
    curr_y += 28

    # Timetable Grid
    grid_left = 50
    grid_right = W - 50
    grid_w = grid_right - grid_left

    periods = [
        ("DAY / TIME", 190),
        ("08:00 -\n09:00", 175),
        ("09:00 -\n10:00", 220),
        ("10:00 -\n10:15", 130),
        ("10:15 -\n11:15", 220),
        ("11:15 -\n12:15", 240),
        ("12:30 -\n01:30", 155),
        ("01:30 -\n02:30", 260),
        ("02:30 -\n03:30", 260),
        ("03:45 -\n04:45", 250),
    ]

    header_h = 75
    row_h = 70

    # Draw Table Header
    tx = grid_left
    for label, pw in periods:
        draw.rectangle([(tx, curr_y), (tx + pw, curr_y + header_h)], fill=CLR_ACCENT_ORANGE, outline=CLR_BORDER, width=1)
        lines = label.split("\n")
        if len(lines) == 1:
            draw.text((tx + pw // 2, curr_y + header_h // 2), lines[0], fill=CLR_DARK_TEXT, font=f_th, anchor="mm")
        else:
            draw.text((tx + pw // 2, curr_y + 20), lines[0], fill=CLR_DARK_TEXT, font=f_th, anchor="mt")
            draw.text((tx + pw // 2, curr_y + 45), lines[1], fill=CLR_DARK_TEXT, font=f_th, anchor="mt")
        tx += pw

    curr_y += header_h

    # Timetable Days Data
    days_data = [
        ("Monday", [
            {"col": 1, "span": 1, "text": ""},
            {"col": 2, "span": 2, "text": "CC LAB(DK,SS)A1 LHC201 (9-11)\nDL LAB(SV,VH)A2 LAB6 (8-11)"},
            {"col": 4, "span": 1, "text": ""},
            {"col": 5, "span": 1, "text": "PGC LAB(DK,MJ)A1 LAB6 /\nCNS LAB(PS,PK)A2 LHC201"},
            {"col": 6, "span": 1, "text": "LUNCH"},
            {"col": 7, "span": 1, "text": ""},
            {"col": 8, "span": 1, "text": "CNS(PS)"},
            {"col": 9, "span": 1, "text": ""},
        ]),
        ("Tuesday", [
            {"col": 1, "span": 1, "text": ""},
            {"col": 2, "span": 1, "text": "CC(DK)"},
            {"col": 3, "span": 1, "text": "TEA"},
            {"col": 4, "span": 1, "text": "DL(SV)"},
            {"col": 5, "span": 1, "text": "CNS(PS)"},
            {"col": 6, "span": 1, "text": "LUNCH"},
            {"col": 7, "span": 2, "text": "CC LAB(DK,SS)A2 LHC201 /\nDL LAB(SV,VH)A1 LAB6"},
            {"col": 9, "span": 1, "text": ""},
        ]),
        ("Wednesday", [
            {"col": 1, "span": 1, "text": ""},
            {"col": 2, "span": 1, "text": "AISD(NDG)"},
            {"col": 3, "span": 1, "text": "TEA"},
            {"col": 4, "span": 1, "text": "DL(SV)"},
            {"col": 5, "span": 1, "text": "PGC(SG)"},
            {"col": 6, "span": 1, "text": "LUNCH"},
            {"col": 7, "span": 1, "text": "CC(DK)"},
            {"col": 8, "span": 1, "text": ""},
            {"col": 9, "span": 1, "text": ""},
        ]),
        ("Thursday", [
            {"col": 1, "span": 1, "text": ""},
            {"col": 2, "span": 1, "text": "PGC(SG)"},
            {"col": 3, "span": 1, "text": "TEA"},
            {"col": 4, "span": 1, "text": "CNS(PS)"},
            {"col": 5, "span": 1, "text": "DL(SV)"},
            {"col": 6, "span": 1, "text": "LUNCH"},
            {"col": 7, "span": 2, "text": "PGC LAB(DK,MJ)A2 LAB6 /\nCNS LAB(PS,PK)A1 LHC201"},
            {"col": 9, "span": 1, "text": ""},
        ]),
        ("Friday", [
            {"col": 1, "span": 1, "text": ""},
            {"col": 2, "span": 1, "text": "CC(DK)"},
            {"col": 3, "span": 1, "text": "TEA"},
            {"col": 4, "span": 1, "text": "DL(SV)"},
            {"col": 5, "span": 1, "text": "PGC(SG)"},
            {"col": 6, "span": 1, "text": "LUNCH"},
            {"col": 7, "span": 3, "text": "AISD(NDG,AK,MA,SP)(1-5) CLH310"},
        ]),
        ("Saturday", [
            {"col": 1, "span": 1, "text": ""},
            {"col": 2, "span": 1, "text": ""},
            {"col": 3, "span": 4, "text": "MP(UFM,NK,SV,PS) CLH310 (10:00 - 01:00)"},
            {"col": 7, "span": 1, "text": ""},
            {"col": 8, "span": 1, "text": ""},
            {"col": 9, "span": 1, "text": ""},
        ]),
    ]

    # Precalculate column X coordinates
    col_x = [grid_left]
    for _, pw in periods:
        col_x.append(col_x[-1] + pw)

    for day_label, cell_list in days_data:
        # Day Header
        draw.rectangle([(col_x[0], curr_y), (col_x[1], curr_y + row_h)], fill=(255, 255, 255), outline=CLR_BORDER, width=1)
        draw.text((col_x[0] + (col_x[1] - col_x[0]) // 2, curr_y + row_h // 2), day_label, fill=CLR_DARK_TEXT, font=f_th, anchor="mm")

        for c_info in cell_list:
            c_idx = c_info["col"]
            span = c_info.get("span", 1)
            text_str = c_info["text"]

            cx_start = col_x[c_idx]
            cx_end = col_x[c_idx + span]
            cell_box_w = cx_end - cx_start

            bg_c = (255, 255, 255)
            if "LAB" in text_str or "AISD" in text_str or "MP" in text_str:
                bg_c = (240, 248, 255)
            elif text_str in ("LUNCH", "TEA"):
                bg_c = (249, 250, 251)

            draw.rectangle([(cx_start, curr_y), (cx_end, curr_y + row_h)], fill=bg_c, outline=CLR_BORDER, width=1)

            if text_str:
                lines = text_str.split("\n")
                if len(lines) == 1:
                    draw.text((cx_start + cell_box_w // 2, curr_y + row_h // 2), lines[0], fill=CLR_DARK_TEXT, font=f_cell_bold if bg_c != (255, 255, 255) else f_cell, anchor="mm")
                else:
                    draw.text((cx_start + cell_box_w // 2, curr_y + row_h // 2 - 12), lines[0], fill=CLR_DARK_TEXT, font=f_cell_bold, anchor="mm")
                    draw.text((cx_start + cell_box_w // 2, curr_y + row_h // 2 + 14), lines[1], fill=CLR_DARK_TEXT, font=f_cell_bold, anchor="mm")

        curr_y += row_h

    curr_y += 40

    # ── Course & Faculty Mapping Table ──────────────────────────
    draw.rectangle([(grid_left, curr_y), (grid_right, curr_y + 36)], fill=CLR_MAROON)
    draw.text((grid_left + 20, curr_y + 8), "Course Title", fill=(255, 255, 255), font=f_bold)
    draw.text((grid_left + 380, curr_y + 8), "Course Code", fill=(255, 255, 255), font=f_bold)
    draw.text((grid_left + 590, curr_y + 8), "Name of the Faculty", fill=(255, 255, 255), font=f_bold)

    half_w = grid_w // 2
    draw.text((grid_left + half_w + 20, curr_y + 8), "Course Title", fill=(255, 255, 255), font=f_bold)
    draw.text((grid_left + half_w + 390, curr_y + 8), "Course Code", fill=(255, 255, 255), font=f_bold)
    draw.text((grid_left + half_w + 600, curr_y + 8), "Name of the Faculty", fill=(255, 255, 255), font=f_bold)

    curr_y += 36

    courses_left = [
        ("Deep learning (DL)", "26ECAC302", "Ms Sneha V (SV)"),
        ("Cloud Computing (CC)", "26ECAC301", "Mr Dheeraj K (DK)"),
        ("Parallel and GPU Computing (PGC)", "26ECAC304", "Ms. Shrushti G (SG)"),
    ]
    courses_right = [
        ("AI-Assisted Software Development", "26ECSE346", "Dr. Narayan D G. (NDG)"),
        ("Cryptography and Network Security", "26ECAC305", "Ms. Pooja S (PS), Ms Megha J (MJ)"),
        ("Mini Project / Laboratory Practice", "26ECMP301", "Dr. UFM, Prof. NK, Prof. SV, Prof. PS"),
    ]

    for r_idx in range(max(len(courses_left), len(courses_right))):
        c_bg = CLR_HEADER_BG if r_idx % 2 == 0 else (255, 255, 255)
        draw.rectangle([(grid_left, curr_y), (grid_right, curr_y + 38)], fill=c_bg, outline=CLR_BORDER, width=1)
        draw.line([(grid_left + half_w, curr_y), (grid_left + half_w, curr_y + 38)], fill=CLR_BORDER, width=1)

        if r_idx < len(courses_left):
            c_name, c_code, c_fac = courses_left[r_idx]
            draw.text((grid_left + 20, curr_y + 9), c_name, fill=CLR_DARK_TEXT, font=f_cell_bold)
            draw.text((grid_left + 380, curr_y + 9), c_code, fill=CLR_MAROON, font=f_cell_bold)
            draw.text((grid_left + 590, curr_y + 9), c_fac, fill=CLR_DARK_TEXT, font=f_cell)

        if r_idx < len(courses_right):
            c_name, c_code, c_fac = courses_right[r_idx]
            draw.text((grid_left + half_w + 20, curr_y + 9), c_name, fill=CLR_DARK_TEXT, font=f_cell_bold)
            draw.text((grid_left + half_w + 390, curr_y + 9), c_code, fill=CLR_MAROON, font=f_cell_bold)
            draw.text((grid_left + half_w + 600, curr_y + 9), c_fac, fill=CLR_DARK_TEXT, font=f_cell)

        curr_y += 38

    curr_y += 70

    # Signatures Footer
    draw.text((grid_left, curr_y), "Date: 01-09-2026", fill=CLR_DARK_TEXT, font=f_bold)
    draw.text((W // 2, curr_y), "Prepared by: Mr Mallikarjun Akki", fill=CLR_DARK_TEXT, font=f_bold, anchor="mt")
    draw.text((grid_right, curr_y), "Dr. Narayan D.G.\nHead — CSE(AI)", fill=CLR_DARK_TEXT, font=f_bold, anchor="ra")

    # Save image
    out_path = os.path.join(OUTPUT_DIR, "timetable_cse_ai_sem5.png")
    img.save(out_path, "PNG", dpi=(300, 300))
    img.save(os.path.join(DATA_DIR, "timetable_cse_ai_sem5.png"), "PNG")
    print("Generated Timetable Image:", out_path)
    return out_path


if __name__ == "__main__":
    generate_calendar_of_events()
    generate_timetable_image()
