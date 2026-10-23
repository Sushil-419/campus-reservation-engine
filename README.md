# Multi-User Resource Reservation & Scheduling Engine

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-336791.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-red.svg)](https://www.sqlalchemy.org/)
[![Tests](https://img.shields.io/badge/Tests-21%20Passed%20(100%25)-brightgreen.svg)]()
[![License](https://img.shields.io/badge/License-MIT-green.svg)]()

> **KLE Technological University — Team 16**  
> **Author:** Sushilendra Ekbote ([@Sushil-419](https://github.com/Sushil-419))

A high-performance campus facility reservation and timetable management engine. Unlike conventional booking systems that perform error-prone availability checks in application code, this platform enforces strict correctness guarantees directly within the **PostgreSQL kernel** using GiST exclusion constraints and deterministic row-level locks.

---

## 📌 Problem Statement

In academic institutions, facilities such as seminar halls, computing labs, classrooms, and sports courts are traditionally scheduled via registers, spreadsheets, or messaging channels. This creates race conditions where two competing requests for the same room and time slot both succeed, resulting in double-bookings.

### The Engineering Solution
1. **Database-Level Mutual Exclusion:** Using PostgreSQL's `EXCLUDE USING gist` on `(resource_id WITH =, during WITH &&)`, overlapping intervals are physically rejected at the database level with SQLSTATE `23P01` (mapped to HTTP `409 Conflict`).
2. **Quota Race Protection:** Before counting a user's active reservations, the transaction acquires a row-level lock (`SELECT ... FOR UPDATE` on the user row), preventing rapid parallel clicks from bypassing booking limits.
3. **Discrete Half-Open Intervals:** All slots use `[)` timestamp ranges (e.g. `[09:00, 10:00)` and `[10:00, 11:00)`), allowing adjacent bookings to succeed without collision.

---

## 🏛️ Campus Resources (368 Facilities)

The engine models 368 real campus resources across KLE Tech buildings:

* **R H Kulkarni:** Classrooms (101–108, 201–208, 301–312), Tinkering Lab, DTSI 1–6 (Project Spaces), Lab 301.
* **CLITE:** Computing Labs (101–108, 201–205), CEVI Lab, AI Research Center, Cloud Computing Center.
* **Main & EEE:** Classrooms across floors 0 and 1 (101–120, 201–220).
* **CLH & Mechanical:** Specialized labs and classrooms.
* **Architecture, Civil, ENC, Biotech:** Department-specific labs, classrooms, and seminar halls.
* **Auditoriums & Sports:** Deshpande Foundation Auditorium, Basketball Court, Tennis Court, Indoor Sports Complex.

---

## 🛡️ Declarative Policy Matrix

Authorization rules are stored declaratively in the `policies` table rather than hardcoded in application logic:

| Resource Type | Student | CR | Faculty | Lab Instructor | HOD | Max Duration | Horizon |
|---|---|---|---|---|---|---|---|
| **Classroom** | `needs_coordinator` | `own_dept` | `direct` | `own_dept` | `direct` | 120 min | 7 days |
| **Project Space** | `needs_guide` | `needs_guide` | `direct` | `direct` | `direct` | 180 min | 14 days |
| **Lab** | `needs_guide` | `needs_guide` | `direct` | `own_dept` | `direct` | 180 min | 14 days |
| **Research Center**| `needs_guide` | `needs_guide` | `direct` | ❌ Not Allowed | `direct` | 180 min | 14 days |
| **Seminar Hall** | `needs_coordinator`| `needs_coordinator`| `direct`| `own_dept` | `direct` | 240 min | 30 days |
| **Auditorium** | `needs_coordinator`| `needs_coordinator`| `direct`| ❌ Not Allowed | `direct` | 240 min | 30 days |
| **Sports** | `direct` | `direct` | `direct` | `direct` | `direct` | 120 min | 7 days |

### Condition Explanations:
* `direct`: Immediate booking with no extra paperwork.
* `own_dept`: Allowed only if the resource belongs to the user's department (or is campus-wide shared).
* `needs_guide`: Requires the email of a valid faculty member or HOD.
* `needs_coordinator`: Requires faculty email + justification purpose ($\ge 10$ characters).

### Active Booking Quotas:
* **Student:** 2 concurrent active bookings
* **CR:** 3 concurrent active bookings
* **Faculty:** 5 concurrent active bookings
* **Lab Instructor:** 5 concurrent active bookings
* **HOD:** 10 concurrent active bookings

---

## 📅 Timetable Bulk Import

The engine supports semester-wide schedule imports via [`scripts/import_timetable.py`](scripts/import_timetable.py):
* Uses set-based PostgreSQL `generate_series` to expand weekly schedules into dated bookings across an entire academic term.
* Automatically filters out national/institutional holidays from `data/holidays.csv`.
* Catches timetable clashes using the exclusion constraint and generates a conflict audit report.

---

## 💻 Tech Stack

* **Backend:** Python 3.11+, FastAPI, Uvicorn (ASGI)
* **Database & ORM:** PostgreSQL 17 + `btree_gist`, SQLAlchemy 2.0, Alembic migrations
* **Driver:** Psycopg 3
* **Security:** Bcrypt password hashing, HttpOnly SameSite session cookies, SQL injection parameterized queries
* **Frontend:** Responsive vanilla HTML5, CSS3, JavaScript (no Node.js build step, zero framework overhead)
* **Testing:** Pytest, HTTPX live test runner

---

## 🚀 Quick Start Guide

### 1. Prerequisites
* Python 3.11+
* Docker & Docker Compose (or local PostgreSQL 17 with `btree_gist`)

### 2. Start PostgreSQL
```bash
docker compose up -d
```

### 3. Setup Virtual Environment
```bash
# Clone the repository
git clone https://github.com/Sushil-419/<repo-name>.git
cd <repo-name>

# Create and activate virtual environment
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 4. Configure Environment
Copy the example environment file:
```bash
cp .env.example .env
```
*(Verify your `DATABASE_URL` matches your local/Docker PostgreSQL credentials)*

### 5. Run Migrations & Seed Campus Data
```bash
# Apply database migrations
python -m alembic upgrade head

# Seed policies, 368 resources, and demo users
python -m scripts.seed_all

# (Optional) Import sample semester timetable
python -m scripts.import_timetable data/sample_timetable.csv --term "2026-odd" --start 2026-08-01 --end 2026-12-01 --holidays data/holidays.csv
```

### 6. Run the Application
```bash
# Windows one-click:
run_server.bat

# Or via terminal:
python run_server.py
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

---

## 🧪 Automated Test Suite

Run the full automated test suite verifying concurrency guarantees, SQL injection resistance, and policy rules:
```bash
pytest tests/ -v
```

### Test Coverage Summary:
* `test_concurrency.py`:
  * 20 parallel threads booking the exact same slot simultaneously $\rightarrow$ exactly **1 succeeds (201)** and **19 rejected (409 Conflict)**.
  * Partial overlapping intervals $\rightarrow$ exactly 1 succeeds.
  * 20 parallel requests for 20 distinct rooms $\rightarrow$ all 20 succeed.
  * Adjacent boundary slots ($[09:00, 10:00)$ and $[10:00, 11:00)$) $\rightarrow$ both succeed.
  * Quota race: parallel requests exceeding quota $\rightarrow$ locked and capped.
* `test_injection.py`: Verifies SQL injection payloads in all text/query parameters are safely treated as literal data.
* `test_negative.py`: Validates 401 unauthenticated, 403 forbidden roles, 400 off-grid/operating hours limits, and unauthorized cancellations.
* `test_timetable.py`: Verifies timetable slot blocking and re-booking lifecycle.

---

## 👥 Demo Accounts

| Role | Email | Password | Permissions |
|---|---|---|---|
| **HOD (Admin)** | `ekbotesushilendr0@gmail.com` | `Admin@123` | Highest privilege, quota 10, cross-department access |
| **Faculty** | `faculty01@example.edu` | `faculty123` | Direct access to classrooms/labs, quota 5 |
| **CR** | `cr01@example.edu` | `cr123` | Direct access to own department classrooms, quota 3 |
| **Lab Instructor** | `lab_instructor01@example.edu` | `instructor123` | Direct access to own department labs, quota 5 |
| **Student** | `student01@example.edu` | `student123` | Requires guide/coordinator for restricted facilities, quota 2 |

---

## 📄 License
This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
