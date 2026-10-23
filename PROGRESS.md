# Development history

The project was first built as a working booking app (FastAPI + PostgreSQL,
real accounts with admin approval, `no_overlap` exclusion constraint, quota
and capacity checks, Groq chatbot). It was then improved in small, verified
phases. Test counts are the `pytest -q` result at the end of each phase; they
match the per-file counts in the current suite (each phase's new test file
adds exactly the difference).

**Phase 0 — Baseline.** Backup of the finished project, `CLAUDE.md`
guardrails for all later work, baseline suite run. **66 tests passed.**

**Phase 1 — Correctness hardening.** Fixed a real bug: the code treated
everything except `cancelled` as active while the database constraints also
excluded `rejected`, so rejected bookings still blocked quota, capacity and
free slots. Introduced one `ACTIVE_STATUSES` constant, an explicit state
machine with row locking (`_apply_status_change`), the `reservation_events`
audit trail, rejection reasons and the history endpoint.
**83 tests** (+17 in `test_lifecycle.py`).

**Phase 2 — Resource policies and blackouts.** Resources got timezone,
opening hours, open weekdays, min/max duration, auto-approve and an active
flag; admin PATCH with safe capacity changes; maintenance blackouts with
atomic forced cancellation; the lock order user → resource with
FOR SHARE / FOR UPDATE; the day-schedule endpoint and a timeline built from
it; an audit-event backfill migration. **109 tests** (+26 in
`test_resources_policy.py`).

**Phase 3 — Scheduling engine.** Pure `scheduler.py` (occupancy profile, free
windows, subtraction, candidates, scoring, ranking), `POST /schedule/suggest`,
alternatives in the 409 response, a flexible booking drawer and a "Find a
slot" tab; all database connections set to UTC. **145 tests** (+22 in
`test_scheduler_unit.py`, +14 in `test_schedule_api.py`).

**Phase 4 — Recurring series and background jobs.** Exclusion constraints
rewritten to the explicit set `IN ('pending','confirmed')`; recurring series
(pure `recurrence.py`, preview, savepoint-based creation, series
cancel/approve/reject, series counted once in the quota); the `expired`
status; a job runner in the FastAPI lifespan with an advisory lock and
`SKIP LOCKED`. **171 tests** (+10 `test_recurrence_unit.py`, +11
`test_series.py`, +5 `test_jobs.py`).

**Phase 5 — Waitlist, real-time, notifications, calendar.** Playwright UI
smoke test (found and fixed a timeline double-render bug); waitlist with FIFO
promotion in a separate transaction; PostgreSQL LISTEN/NOTIFY → Server-Sent
Events with a live indicator; after-commit email queue (savepoint-safe);
hand-written iCalendar export and a private calendar feed. **195 tests**
(+11 `test_waitlist.py`, +6 `test_realtime.py`, +7
`test_notifications_ics.py`).

**Phase 6 — Analytics, demo data, benchmark, property tests.** Admin
analytics (utilization, heatmap, approval latency, waitlist stats, CSV) with an
Analytics tab; `scripts/seed_demo.py`; the naive-vs-engine benchmark;
Hypothesis property tests against brute-force oracles; the e2e smoke test
moved into `tests/e2e/`; `run_all_checks.sh/.bat`. **204 tests** (+3
`test_analytics.py`, +6 `test_properties.py`).

**Phase 7 — Documentation.** README rewritten (generated API reference and
settings table), ER diagram generated from the real schema, engineering notes
with viva Q&A, demo script, report material, `.env.example` and
`docker-compose.yml` brought up to date, chatbot knowledge updated, fresh
report screenshots. No application logic changed. **204 tests passed.**

## Upgrade (ten phases)

The finished app was then upgraded towards a full scheduling engine, again
in small verified phases. Each phase started from a green suite and kept
every endpoint, response field and HTML id.

**Upgrade 1 — Security and correctness hardening.** Case-insensitive unique
emails (`lower(email)` index), email validation, safe Google account
linking, CSV formula-injection and HTML-escaping fixes, single-use tokens
consumed with one conditional UPDATE, denying a member releases sessions,
bookings, series and waitlist entries, input bounds. A Python 3.12 venv for
macOS. **267 tests** (+63, mostly `test_hardening.py`).

**Upgrade 2 — Capacity models.** `booking_mode` (`whole` rooms vs `units`
pools) and `party_size` on bookings, series and waitlist entries;
`is_exclusive` (capacity 1 or whole) feeds `no_overlap`; the weighted sweep
line for pools; peek-then-lock with a re-check; safe mode and capacity
changes; capacity and mode fields in the admin form. **297 tests** (+30).

**Upgrade 3 — User groups and the priority waitlist.** `user_groups`
(Student / Staff / Faculty with priority, quota, horizon, maximum length),
restricted resources, group rules checked under the user lock, the
waitlist ordered by priority with aging (one SQL order for promotion and
position). **317 tests** (+20).

**Upgrade 4 — Pre-emption with re-accommodation.** Faculty can take an
exclusive slot from lower-priority bookings with ≥ 24 h notice, all or
nothing, under one lock order; victims become `preempted` and are moved to
the best same-day alternative (or the waitlist) after the commit. Tests no
longer send real email. **333 tests** (+16).

**Upgrade 5 — Bundles and common slots.** `reservation_bundles`,
all-or-nothing booking of several resources with an ascending-id lock order
(deadlock-free), common free slots by interval intersection including
participants' free time, editable `can_preempt`, a global `[hidden]` CSS fix.
**355 tests** (+22).

**Upgrade 6 — Allocation engine core.** Pure `allocator.py` with greedy,
local search and branch-and-bound solvers, a shared feasibility checker,
explanations, and `scripts/benchmark_allocator.py`. **370 tests** (+15).

**Upgrade 7 — Allocation rounds.** Rounds and requests tables, member and
admin Allocation tabs, solve / compare all / commit (savepoint per item,
round → users → resources lock order), the job closes due rounds; warm start
and forward-checking bound for branch-and-bound. **385 tests** (+15).

**Upgrade 8 — Resource Board and Race Lab.** A board view (day / week,
privacy-preserving for members, approve from a popover), the admin Race Lab
(N simultaneous real bookings, exactly the allowed winners), and the cause
of rare flaky runs fixed (concurrent pytest processes on one test database
→ a session advisory lock in `conftest.py`). **394 tests** (+9).

**Upgrade 9 — Check-in, no-shows and fairness.** `requires_checkin`, a
check-in window, the job releases no-shows with `SKIP LOCKED` and promotes
the waitlist, a no-show reputation penalty on waitlist priority and
allocation weight, fairness analytics with Jain's index, admin UI polish.
**402 tests** (+8).

**Upgrade 10 — Documentation and final check.** Tests that book now use
dates relative to today (`tests/dates.py`); the board scrolls long days to
the current time; demo data feeds every analytics section (check-in
no-shows, past pre-emptions and waitlist promotions, a bundle, the open
round); README, ER diagram, engineering notes (+25 viva questions),
report material, demo script and a one-page viva cheat sheet rewritten;
chatbot knowledge, `.env.example` and `docker-compose.yml` updated.
**402 tests passed.**
