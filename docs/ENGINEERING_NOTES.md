# Engineering notes

One section per improvement phase: what changed, and why. The first part
covers the original build; the part "Upgrade phases" covers the ten-phase
upgrade (groups, capacity models, pre-emption, bundles, allocation rounds,
board, Race Lab, check-in and fairness). Viva questions 26–50 are about the
upgrade.

---

## Phase 1: Correctness hardening (reservation lifecycle)

### 1. The bug

A reservation can be `pending`, `confirmed`, `cancelled` or `rejected`.
Only the first two should "hold" a slot.

The database already knew this. Migration `e8a1f2b3c4d5` added the
`rejected` status and changed both EXCLUDE constraints (`no_overlap`,
`no_user_duplicate_reservation`) to `WHERE status != 'cancelled' AND
status != 'rejected'`.

The application code was never updated. It still filtered with
`status != cancelled` in four places, so a **rejected** booking was still
treated as active:

| Where | Effect of the bug |
|---|---|
| `_count_active_reservations` (quota) | A rejected booking still used up one of the user's 5 quota places |
| `_peak_overlapping_reservations` (capacity > 1) | A rejected booking still took a seat on shared resources |
| `user_duplicate` check in `create_reservation` | A user could not re-book a slot after being rejected for it |
| `compute_free_slots` | The slot still showed as taken in the timeline |
| `static/app.js` `loadTimeline` | The UI still drew rejected bookings as occupying the slot |

**Why it happened:** the rule "what counts as active" was written out by
hand in several places: once in SQL (the constraints) and four times in
Python. When a new status was added, only the SQL copy was updated. The
copies **drifted apart**, and nothing failed loudly: the DB constraint
was *looser* than the app checks, so the app simply refused bookings it
should have allowed.

> **Later change (Phase 4):** migration `d2f6b8a0c4e1` rewrote both exclusion
> constraints to use the explicit whitelist `status IN ('pending','confirmed')`,
> so the database definition of "active" is now *identical* to
> `ACTIVE_STATUSES`. The new `expired` status (Phase 4) is therefore inactive
> everywhere automatically.

### 2. The fix: one source of truth

`app/models/reservation.py` now defines:

```python
ACTIVE_STATUSES = (ReservationStatus.pending, ReservationStatus.confirmed)
```

Every query uses `Reservation.status.in_(ACTIVE_STATUSES)`. The frontend
has the same list (`const ACTIVE_STATUSES = ["pending", "confirmed"]`).

Why this works:
- **Whitelist instead of blacklist.** `!= cancelled` means "everything
  except cancelled", so any new status is active by default. `in
  (pending, confirmed)` means "only these", so a new status is
  inactive until someone deliberately adds it.
- **One place to change.** If the rule changes, you edit one tuple, not
  four queries.
- The comment above the constant points to the constraint migration, so
  whoever changes one is reminded to check the other.

The EXCLUDE constraints themselves were **not** changed; they were
already correct.

### 3. The state machine

Before, each of `cancel_reservation`, `approve_reservation` and
`reject_reservation` did its own `if status != ...` check, and cancel did
no check at all (you could "cancel" a rejected reservation). Now there is
an explicit table of allowed moves:

```
pending   -> confirmed, rejected, cancelled
confirmed -> cancelled
cancelled -> (none, terminal)
rejected  -> (none, terminal)
```

Two time rules sit on top of the table:
- You cannot **cancel** once `end_time <= now` (the booking is over).
- You cannot **approve** once `start_time <= now` (too late to confirm).

Any other move raises `InvalidStateError`, which the routes return as
**HTTP 409 Conflict**. 409 means "your request conflicts with the
current state of the resource", which is the right code. (Approve and
reject used to return 400 for this. No existing test depended on that.)

### 4. Why the row lock prevents approve/cancel races

All three operations call one helper, `_change_status()`, which:

1. Loads the reservation with `SELECT ... FOR UPDATE` (row lock).
2. Checks 404 and 403 (only owner or admin may cancel).
3. Checks the move against `ALLOWED_TRANSITIONS` and the time rules.
4. Sets the new status **and** writes an audit event.
5. Commits (which releases the lock). Any error rolls back instead.

**The race without the lock:** the admin clicks *Approve* while the member
clicks *Cancel* at the same moment. Both requests read
`status = pending`, both think their move is valid, and both write. Whoever
commits last wins, so the reservation could end up `confirmed` even though
the member cancelled it. Both would also log a transition from `pending`,
which is nonsense.

**With the lock:** the second request blocks at step 1 until the first one
commits. It then reads the *new* status (`cancelled`) and step 3 refuses
`cancelled -> confirmed` with a 409. The two changes run one after the
other, never interleaved. `test_concurrent_status_changes_are_serialised`
proves it: it holds the lock in one session, shows that an approve in a
second session waits, then shows the approve fails cleanly once the first
session commits a cancel.

This is the same `SELECT ... FOR UPDATE` technique the project already uses
for the quota (locks the user row) and capacity (locks the resource row)
checks. It only blocks requests for the *same* reservation.

### 5. The audit trail

New table `reservation_events` (migration `f3a9c1d7b2e6`):

| Column | Meaning |
|---|---|
| `reservation_id` | Which reservation (FK, indexed for fast history lookups) |
| `actor_user_id` | Who did it (FK to users, nullable) |
| `from_status` | Previous status; `NULL` means "just created" |
| `to_status` | New status |
| `reason` | Optional text, used for rejection reasons |
| `created_at` | When (DB default `now()`) |

It reuses the existing Postgres enum type `reservation_status`
(`create_type=False`), so there is only one list of statuses in the DB.

**When events are written:**
- On creation (`NULL -> pending`, actor = the booking user). The
  reservation is `flush()`ed to get its id, the event is added, then both
  are committed together.
- On every transition, inside `_change_status()`, in the same
  transaction as the status change.

Because the event and the change share one transaction, they succeed or
fail together. You can never have a status change with no event, or an
event for a change that was rolled back.

**Reading it:** `GET /reservations/{id}/history` returns events oldest
first. Only the owner or an admin may read it (403 otherwise, 404 if the
id doesn't exist).

**Reject reason:** `POST /reservations/{id}/reject` accepts an optional
body `{"reason": "..."}` (max 500 chars, blank becomes `null`). With no
body it still works.

#### Decision: `rejection_reason` is derived, not stored twice

`ReservationOut.rejection_reason` is a SQLAlchemy `column_property`: a
small subquery that reads the reason from the latest `-> rejected` event.
It is not a second column on `reservations`.

Why this is the simpler option:
- **No duplicated data.** The reason lives only in `reservation_events`.
  A copy in a second column would have to be kept in sync by hand, and
  two copies drifting apart is exactly the bug this phase fixes.
- **No extra write path.** `_change_status()` writes the event and that
  is all; nothing else needs updating.
- **No N+1 queries.** Because it is a `column_property`, the subquery is
  part of the same `SELECT` that loads the reservation, so listing 500
  reservations is still one query.
- `rejected` is terminal, so there is at most one rejected event per
  reservation anyway.

### 6. Frontend

- The timeline only treats `pending` and `confirmed` reservations as
  occupying a slot.
- Admin "Pending approvals": an optional *Reason* text box next to
  *Reject*, sent as the request body.
- "My reservations": rejected items show `Reason: ...` underneath. The
  *Cancel* button only appears for active reservations that haven't
  ended, matching the server-side rules.

### 7. Tests

`tests/test_lifecycle.py` (17 tests) covers: rejected bookings no longer
blocking quota, capacity, free slots or same-user re-booking; every
invalid transition returning 409, including cancelling an ended booking
and approving a started one; 404 still returned for unknown ids; the
lock serialising concurrent changes; and history contents, actors,
reasons and access control. The four "rejected is inactive" tests were
confirmed to **fail** on the pre-phase code and pass after the fix.

---

The sections below follow the same pattern for each later design topic:
**Problem → Design → Alternatives considered → Where in code → How it is tested.**

## 2. No double-booking: exclusion constraints

**Problem.** "Check for an overlap, then insert" has a gap between the check
and the insert. Two concurrent requests can both pass the check and both
insert (a TOCTOU race).

**Design.** Two PostgreSQL `EXCLUDE USING gist` constraints on
`reservations`:
- `no_overlap`: `(resource_id WITH =, tstzrange(start_time, end_time) WITH &&)`
  for rows that are active **and** `exclusive` (capacity-1 resources).
- `no_user_duplicate_reservation`: `(resource_id =, user_id =, tstzrange &&)`
  for all active rows.

The database rejects a conflicting `INSERT`/`UPDATE` with SQLSTATE `23P01`;
the service turns that into HTTP 409. `exclusive` is stamped on each row at
insert time (`capacity == 1`; since upgrade phase 2 `is_exclusive(resource)`
= capacity 1 **or** booking mode `whole`) because a constraint predicate
cannot look at another table.

**Alternatives rejected.** A Python lock only works inside one process. A
Redis lock adds a component and still depends on every code path using it. A
`SERIALIZABLE` transaction would also work, but needs retry loops everywhere
and gives worse error messages.

**Where.** Migrations `9bedad9ecc01` (first `no_overlap`), `09f6550df343`, `c7d2e4f8a1b2`, `e8a1f2b3c4d5`,
`d2f6b8a0c4e1`; `app/services/reservations.py:create_reservation`.

**Tested.** `tests/concurrency_test.py` (20 real parallel HTTP requests → 1
winner); benchmark scenario B; `test_reservations.py`, `test_lifecycle.py`.

## 3. Capacity > 1 and the per-user quota: row locks + sweep line

**Problem.** "At most N bookings at once" and "at most 5 active bookings per
user" cannot be written as an exclusion constraint.

**Design.** Serialise only the competing requests with short row locks:
- quota: `SELECT … FROM users WHERE id = :u FOR UPDATE`, then count;
- capacity: `SELECT … FROM resources WHERE id = :r FOR UPDATE`, then compute
  the **peak concurrency** in the requested range with a sweep line
  (`free_slots.py:peak_concurrency`): turn every overlapping booking into
  `+1` at its start and `−1` at its end, sort (ends before starts at the
  same instant, so 9–10 and 10–11 don't overlap) and track the maximum.

A recurring series counts as **one** toward the quota:
`count(singles) + count(DISTINCT series_id)` over active future rows
(`_count_active_reservations`).

**Alternatives rejected.** Counting all overlapping bookings over-counts
(9–10 and 10–11 both touch 9–11 but never run at the same time). Locking a
whole table would serialise unrelated users and resources.

**Where.** `reservations.py:create_reservation`, `_book_locked_occurrence`,
`_count_active_reservations`.

**Tested.** `tests/quota_race_test.py`, `tests/capacity_race_test.py`,
`test_capacity.py`, `test_series.py::test_series_counts_as_one_for_quota`,
property test `test_peak_concurrency_matches_brute_force`.

## 4. Lock order and FOR SHARE vs FOR UPDATE

**Problem.** Different operations lock several rows. If two transactions
lock the same rows in opposite orders, they deadlock.

**Design.** One global order: **user → resource**, and for blackouts
**resource → reservations**. A booking takes exactly one resource lock,
chosen by capacity, which is peeked *without* a lock first:
- capacity 1 → `FOR SHARE`: many bookings may proceed together (the
  exclusion constraint already decides who wins), but a blackout or PATCH,
  which needs `FOR UPDATE`, must wait until the booking commits. So a
  blackout cannot slip in between "check blackouts" and "insert".
- capacity > 1 → `FOR UPDATE`: the peak check needs real serialisation.

A lock is never upgraded from SHARE to UPDATE (two holders upgrading would
deadlock). If capacity crossed the 1 / >1 line between the peek and the lock,
the request gets a 409 "please try again".

**Where.** `reservations.py:create_reservation`, `_lock_user_and_resource`,
`_lock_resource_for_share`, `_lock_resource_for_update`.

**Tested.** `test_resources_policy.py::test_blackout_waits_for_in_flight_booking_share_lock`.

## 5. Resource policies and safe edits

**Problem.** Resources need opening hours, open weekdays, durations, a
timezone and an active flag; editing a resource must not invalidate bookings
already made.

**Design.** `_validate_resource_policy` runs with the resource row locked:
active, duration within `[min, min(max, MAX_BOOKING_DURATION_HOURS)]`, same
local date, open weekday, inside opening hours (all in the resource's
timezone), no blackout overlap. `PATCH /resources/{id}` locks the resource
`FOR UPDATE` and refuses (409) to cross the capacity 1 / >1 boundary while
future active bookings exist (their `exclusive` flag would become wrong) or to
go below the current peak. Weekdays are stored as a 7-bit mask.

**Where.** `reservations.py:_validate_resource_policy`,
`resources.py:update_resource`, `_check_capacity_change`.

**Tested.** `test_resources_policy.py` (26 tests).

## 6. Blackouts and atomic forced cancellation

**Problem.** Maintenance windows must block new bookings; existing bookings
in the window must either stop the blackout or be cancelled — never "half
done".

**Design.** `create_blackout` locks the resource `FOR UPDATE`, then the
conflicting active reservations `FOR UPDATE` in id order. Without `force` it
returns 409 with the conflicting ids. With `force=true` it cancels each one
through `_apply_status_change` (reason "cancelled: maintenance — …") and
inserts the blackout in the **same** transaction: everything commits or
nothing does.

**Where.** `resources.py:create_blackout`.

**Tested.** `test_resources_policy.py::test_blackout_force_is_atomic`
(a simulated failure on the second cancellation leaves everything untouched).

## 7. Recurring series and savepoints

**Problem.** A weekly booking is many reservations. Either all must succeed
(all-or-nothing), or the free ones should be booked and the taken ones
skipped — inside one transaction.

**Design.** `expand_series` (pure, `recurrence.py`) turns the rule into UTC
intervals, computed in the **resource's** timezone so 10:00 stays 10:00 local
across DST changes; limits 26 occurrences / 90 days. `create_series` takes the
user and resource locks once, checks quota once, inserts the series row, then
books each occurrence inside a **SAVEPOINT** (`db.begin_nested()`). In
PostgreSQL any failed statement (for example the exclusion violation)
aborts the whole transaction; rolling back to the savepoint undoes only that
occurrence. All-or-nothing raises on the first failure (full rollback);
skip-conflicts records it and continues.

**Alternatives rejected.** One transaction per occurrence (not atomic);
pre-checking everything and then inserting (still racy).

**Where.** `recurrence.py:expand_series`, `series.py:create_series`,
`reservations.py:_book_locked_occurrence`.

**Tested.** `test_recurrence_unit.py`, `test_series.py`, property
`test_expand_series_properties`.

## 8. Background jobs: advisory lock and SKIP LOCKED

**Problem.** Pending bookings whose start time has passed can never be
approved and should be expired; expired sessions/tokens should be cleaned.
With several server processes, the job must not run twice at once, and it
must not wait behind an admin who is approving a row right now.

**Design.** An asyncio loop started in the FastAPI lifespan runs
`run_all_jobs` every `JOB_INTERVAL_SECONDS` in a thread. Its transaction
first calls `pg_try_advisory_xact_lock(<fixed key>)`; if another worker holds
it, the run returns `{"skipped": …}` immediately. Expiry selects
`… FOR UPDATE SKIP LOCKED LIMIT 500`: rows locked by another transaction are
skipped, not waited for; the next tick picks them up. Failing ticks are
logged and never crash the app.

**Alternatives rejected.** cron (outside the app, needs its own deployment);
a single designated worker (breaks when that worker dies); `NOWAIT` (raises
an error instead of skipping).

**Where.** `jobs.py:run_all_jobs`, `expire_stale_pending`, `job_loop`;
`main.py:lifespan`.

**Tested.** `test_jobs.py` (concurrent runs → exactly one executes;
SKIP LOCKED leaves a locked row pending).

## 9. Waitlist and promotion outside the cancel transaction

**Problem.** When a slot frees up, the first person waiting should get it —
without double promotion, without overfilling, and without deadlocks.

**Design.** Joining uses the same policy validator as booking and is only
allowed when the slot is full for that user; at most
`MAX_WAITLIST_ENTRIES_PER_USER`; a partial unique index blocks duplicate
waiting entries. Promotion (`promote_waitlist`) runs in its **own
transaction after** the freeing transaction committed: waiting entries
`FOR UPDATE SKIP LOCKED` in FIFO order → their users `FOR UPDATE` in id order →
the resource (SHARE/UPDATE rule). Each candidate is checked against quota and
booked through `_book_locked_occurrence` inside a savepoint; failures stay
waiting. It is triggered after single cancel, reject, series cancel/reject,
forced blackouts and the expiry job, plus a job safety net.

Why not inside the cancel? The cancel path holds a reservation lock, while
blackout creation locks resource → reservations; taking user/resource locks
inside the cancel would invert that order and could deadlock. A promotion
failure is logged and never turns a successful cancel into an error.

**Where.** `waitlist.py:join_waitlist`, `promote_waitlist`,
`promote_after_commit`; routes in `routes/reservations.py`, `routes/series.py`,
`routes/resources.py`.

**Tested.** `test_waitlist.py` (11 tests, including two parallel cancellations
on a capacity-2 slot → exactly the first two entries promoted, never more than
capacity).

## 10. Real-time updates: LISTEN/NOTIFY → SSE

**Problem.** Other users' changes should appear without reloading, also when
the server runs several workers.

**Design.** Every change calls `pg_notify('reservation_changes', json)`
**inside** its transaction (`_record_event`, blackouts, waitlist). PostgreSQL
delivers a NOTIFY only when the transaction commits and drops it on rollback.
Each worker runs one async psycopg connection with `LISTEN` (reconnecting with
backoff) and pushes payloads into a broadcaster with a bounded queue per SSE
client (slow clients lose events instead of growing memory). `GET /events`
streams `event: change` lines plus a `: ping` every 15 s. Members receive only
`{resource_id, kind}`; admins the full payload. The browser reloads the
affected panels (debounced 300 ms).

**Alternatives rejected.** Polling (wasteful, delayed); WebSockets (two-way,
more complex than needed); an in-process event bus (only reaches clients on
the same worker).

**Where.** `realtime.py`, `routes/events.py`, `main.py:lifespan`, `static/app.js:startLiveUpdates`.

**Tested.** `test_realtime.py` (commit vs rollback with a real LISTEN
connection, payload filter, broadcaster bound, LISTEN loop end to end).

## 11. Emails only after commit

**Problem.** Sending mail inside a transaction holds locks while talking to
SMTP and can announce changes that are later rolled back.

**Design.** `queue_email` appends to `session.info["pending_emails"]`. A
SQLAlchemy `after_commit` listener hands the batch to a background thread; a
rollback of the outermost transaction discards it. Subtle detail found while
building it: both events also fire for **savepoints**, so the code ignores
`after_commit` while `session.in_nested_transaction()` and only discards on
`after_soft_rollback` of the outermost transaction. A send failure is logged,
never raised. One summary email per series action.

**Where.** `notifications.py`, callers in `reservations.py`, `series.py`,
`resources.py`, `waitlist.py`, `jobs.py`.

**Tested.** `test_notifications_ics.py` (queued on approve/reject, nothing on
rollback, savepoint cases, one email per series action).

## 12. Scheduling engine (suggestions)

**Problem.** Users want "the best free slot", not just yes/no.

**Design.** A pure pipeline in `scheduler.py`: `occupancy_profile` (sweep
line, O(n log n)) → `free_windows` (O(n)) → `subtract_intervals` (blackouts,
the past, the caller's own bookings; O(b log b + w + b)) → `candidate_slots`
(15-minute clock alignment, O(free time / 15 min)) → `score_candidate`
(O(1)) → `rank` (sort by score, start, resource id; deterministic). Score
(lower is better) = `1.0·minutes from preferred time + 60·day offset +
30·capacity waste + fragmentation (+30 per unusable leftover gap, −15 if
flush)`. One query for reservations and one for blackouts per resource over
the whole range. On a 409 for overlap/capacity/blackout, the booking route
calls `alternatives_for_conflict` (same resource and day first, then other
resources of the same type) after the failed transaction rolled back.

**Alternatives rejected.** Trying every minute (slow, ugly times); a database
query per day (N+1 queries).

**Where.** `scheduler.py`, `schedule_service.py`, `routes/schedule.py`,
`routes/reservations.py:create_reservation`.

**Tested.** `test_scheduler_unit.py` (22, no database), `test_schedule_api.py`
(14), five Hypothesis properties against brute-force oracles.

## 13. Analytics

**Design.** One SQL query per metric over a range of whole UTC days (at most
92). Booked hours use `upper(r * range) - lower(r * range)` with
`tstzrange` intersection, so bookings crossing the range edge are clipped.
Open hours are computed in Python per resource in its own timezone (open
weekdays × opening hours) minus blackouts (`subtract_intervals`). The heatmap
is one query: `generate_series` over each resource's *local* hourly buckets
joined to overlapping bookings (local buckets, because a UTC hour bucket would
straddle two local hours in Asia/Kolkata, UTC+05:30). Approval latency uses
`percentile_cont(0.5)` between the creation event and the pending → confirmed
event (auto-approved bookings have no such event, so they are excluded).

**Where.** `analytics.py`, `routes/analytics.py`.

**Tested.** `test_analytics.py` (exact numbers on a hand-built dataset).

## 14. Benchmark

`scripts/benchmark_naive_vs_engine.py` makes the race visible: N threads hit
one slot at once. The naive check-then-insert (with a 20 ms pause to widen the
race window) accepted up to 50 of 50; the engine always exactly 1 (capacity 1)
or 5 (capacity 5); N bookings on N different resources all succeed in about
the same wall time, showing that unrelated work is not serialised. See the
README for the latest numbers.

# Upgrade phases

The project was then upgraded in ten phases. Each section below follows the
same pattern: **Problem → Design → Alternatives considered → Where in code →
How it is tested.** Test counts are the suite size at the end of each phase.

## U1. Security and correctness hardening (204 → 267 tests)

**Problem.** `Alice@x.com` and `alice@x.com` could become two accounts;
user-supplied names went unescaped into HTML emails and unneutralised into
CSV cells (formula injection in Excel); an email token could be consumed
twice by two parallel clicks; denying a member left their bookings, series
and waitlist entries alive; several inputs had no bounds.

**Design.** A unique expression index on `lower(email)` plus normalisation in
`security.normalize_email`; `html.escape` in every email template; a
`_csv_safe` single-quote prefix for text cells that start like a formula
(`=`, `+`, `-`, `@`, tab, carriage return); single-use
tokens consumed with one conditional `UPDATE … WHERE used_at IS NULL`, so the
database decides which of two parallel requests wins; `deny_user` revokes
sessions and releases bookings, series and waitlist entries in one
transaction, under the user lock; Pydantic bounds on names, lengths and
`slot_minutes`.

**Alternatives considered.** Lower-casing only in Python (a direct SQL insert
or an old row could still differ in case); `SELECT` then `UPDATE` for tokens
(the classic check-then-act race).

**Where.** Migration `d1e3f5a7b9c2`; `services/security.py`,
`services/users.py:deny_user`, `services/auth_service.py`,
`routes/analytics.py` (CSV), `services/email_service.py`.

**Tested.** `test_hardening.py` (62 tests, including
`test_parallel_token_consumption_succeeds_exactly_once` and
`test_deny_user_revokes_sessions_bookings_series_and_waitlist`).

## U2. Capacity models: whole rooms and unit pools (→ 297 tests)

**Problem.** "Capacity 8" meant two different things: a meeting room for 8
people that one group takes entirely, and a pool of 8 projectors that
several people share. The original model only knew "capacity 1 = exclusive,
otherwise count bookings", and every booking counted as one.

**Design.** `resources.booking_mode` (`whole` | `units`) and
`party_size` on reservations, series and waitlist entries.
`is_exclusive(r) = capacity == 1 or booking_mode == whole`, stamped on the
row, so a whole room is protected by the same `no_overlap` constraint as a
capacity-1 room, and its capacity only limits the party size. For pools the
sweep line became **weighted**: `+party_size` at a start, `−party_size` at an
end; a booking fits if `peak + party ≤ capacity`. Because the lock depends on
exclusivity, the booking peeks at it without a lock, takes FOR SHARE or FOR
UPDATE, and re-checks under the lock (409 "please try again" if it changed).
Mode and capacity edits are refused if a future booking would break.

**Alternatives considered.** A separate "units" table with one row per unit
(heavy, and a party of 3 would need 3 rows); counting bookings instead of
units (wrong for parties).

**Where.** Migration `e5f7a9c1b3d4`; `models/resource.py:is_exclusive`,
`free_slots.py:peak_concurrency`, `scheduler.py:occupancy_profile`,
`free_windows(profile, capacity, need)`, `reservations.py:_party_fits`.

**Tested.** `test_capacity_model.py` (26), the weighted property tests in
`test_properties.py`, concurrent whole / units bookings.

## U3. User groups, priorities and the priority waitlist with aging (→ 317)

**Problem.** Everyone was treated the same: one quota, no horizon, FIFO
waitlist. A college needs Students, Staff and Faculty with different rights,
and resources only some groups may use.

**Design.** `user_groups` (priority, quota, horizon, maximum booking length,
later `can_preempt`) and `users.group_id` (default Student);
`resource_allowed_groups` for restricted resources. Group rules are checked
after the user row is locked, so a concurrent approve / move / deny cannot
slip in. The waitlist is ordered by one SQL expression, `waitlist_order()`,
used by both promotion and `position_of`, so "your position" and the real
order can never disagree: effective priority =
`greatest(0, priority + aging × hours waited − penalty × no-shows)`, then
join time, then id.

**Alternatives considered.** Strict priority (a Student could starve
forever); a role enum instead of a table (no per-group policy, no admin
editing); computing positions in Python (could drift from the SQL order).

**Where.** Migration `f8a1c3e5b7d9`; `models/group.py`, `services/groups.py`,
`reservations.py:_validate_user_policy`, `waitlist.py`.

**Tested.** `test_groups.py` (20), e.g.
`test_aging_lets_a_long_waiting_student_beat_fresh_faculty`,
`test_position_of_matches_promotion_order_for_mixed_groups`.

## U4. Pre-emption with re-accommodation (→ 333)

**Problem.** A Faculty lecture must be able to take a room a Student booked,
without the Student silently losing out, and without races.

**Design.** `POST /reservations` with `preempt=true` for `can_preempt`
groups. One transaction: requester's user row FOR UPDATE → the resource FOR
UPDATE (never SHARE → UPDATE) → the overlapping active reservations FOR
UPDATE ordered by id; then every victim must satisfy the rules (strictly
lower priority, at least 24 h notice, not a bundle item, not the
requester's own, exclusive resource) or nothing changes. Victims become
`preempted` with `preempted_by_id`; because the constraints only see
`pending` / `confirmed`, the slot is free in the same statement. After the
commit, each victim gets its own transaction: the best same-day suggestion
of the same type is booked with the victim's previous status, else the
victim joins the waitlist for the lost slot; an email explains what
happened. Test isolation fix in the same phase: the test run now blanks the
SMTP settings, after discovering tests had sent real email through `.env`.

**Alternatives considered.** Cancelling victims (loses the reason and the
link); re-accommodating inside the pre-emption transaction (would need more
locks in a different order → deadlock risk, and a failure there would undo
the pre-emption).

**Where.** Migration `a7c9e1b3d5f2`; `services/preemption.py`.

**Tested.** `test_preemption.py` (16), including
`test_victim_cancel_racing_a_preemption_stays_consistent` and
`test_no_alternative_puts_victim_on_waitlist_and_cancel_gives_it_back`.

## U5. Bundles and common free slots (→ 355)

**Problem.** A seminar needs the hall **and** a projector **and** two
people's free time. Booking them one by one can leave half a booking.

**Design.** `POST /schedule/common-slots`: per resource, free windows with
room for its party (opening hours − blackouts − bookings); per participant,
the complement of their bookings; then `intersect_windows`, a k-way
two-pointer intersection, then the usual candidates and scoring.
`POST /reservations/bundle` books all items in one transaction; any failure
rolls everything back. **Deadlock prevention:** the user is locked first,
then the resources in **ascending id** order (each FOR SHARE or FOR UPDATE
as for a single booking), so two bundles over the same resources always
queue in the same order. System actions (blackout, expiry, deny) never lock
the bundle row, which avoids a lock-order inversion with the owner's cancel.

**Alternatives considered.** Locking in request order (two bundles {A,B}
and {B,A} deadlock — reproduced during development by a negative control
with the ordering removed); a global "bundle lock" (serialises unrelated
bundles).

**Where.** Migration `b9d1f3a5c7e9`; `services/bundles.py`,
`schedule_service.py:common_slots`, `scheduler.py:intersect_windows`.

**Tested.** `test_bundles.py` (20), e.g.
`test_opposite_order_bundles_never_deadlock[whole|units]`,
`test_one_conflicting_item_creates_nothing_and_offers_alternatives`;
property test `test_intersect_windows_matches_brute_force`.

## U6. Allocation engine core (→ 370)

**Problem.** First-come-first-served is unfair when many requests arrive for
the same week (lab sessions, exam rooms): whoever clicks first wins, even if
a better arrangement serves more people.

**Design.** A pure module `allocator.py`: requests with several acceptable
placements, an objective Σ(1000 × weight − cost) that always prefers one
more allocation over any cost saving, and three solvers — greedy (priority
order, then fewest options), local search (relocate + one-step ejection
chain) and a depth-first branch-and-bound with an optimistic bound and limits
(nodes, time) that reports honestly whether it proved optimality. A
feasibility checker shared by all solvers (exclusive resources, weighted
pools, one placement per person at a time, quotas). A benchmark script.

**Alternatives considered.** An ILP / CP solver library (a new dependency,
and less explainable in a viva); greedy only (provably suboptimal, see the
tests); random restarts (not deterministic).

**Where.** `services/allocator.py`, `scripts/benchmark_allocator.py`.

**Tested.** `test_allocator_unit.py` (15),
`test_allocator_properties.py` (optimal = brute force on small instances).

## U7. Allocation rounds (→ 385)

**Problem.** The engine needs a workflow: collect requests until a deadline,
solve, let the admin compare and commit, explain the result.

**Design.** `allocation_rounds` (open → closed → solved → committed /
cancelled) and `allocation_requests` (resource or type, 1–5 windows,
duration, party, preferred time). The job loop closes rounds whose deadline
passed. Solve builds the problem from the database (existing bookings and
blackouts become busy time; weights from group priority and no-shows).
**Commit**: round row FOR UPDATE → users by id → resources by id (the bundle
helper) → one SAVEPOINT per item, re-validating quota, approval and the slot
under the locks, so a slot taken after solving drops only that request.
Branch-and-bound got a **warm start** (the better of greedy and local search)
and a **forward-checking bound** (each remaining request's best placement that
is still feasible), which cut the explored nodes about 4×.

**Alternatives considered.** Committing without savepoints (one late
conflict would cancel the whole round); re-solving at commit time (results
could change after the admin approved them).

**Where.** Migration `c1e3a5b7d9f1`; `services/allocation_rounds.py`,
`routes/allocation.py`.

**Tested.** `test_allocation_rounds.py` (14), e.g.
`test_greedy_allocates_fewer_than_optimal`,
`test_slot_taken_between_solve_and_commit_only_drops_that_request`.

## U8. Resource Board and Race Lab (→ 394)

**Problem.** Nobody could see all resources at once; and the core claim
("exactly one wins") was only visible in terminal scripts.

**Design.** `GET /schedule/board`: every visible resource with its open
windows, blackouts, bookings and (for pools) the weighted load. Privacy is
decided on the server: members get their own bookings plus anonymous
`{start, end, busy}` blocks — no names, ids or statuses. The Race Lab
(`POST /admin/race-lab/run`) creates a sandbox resource and N members,
releases N threads with a `threading.Barrier` so they call the real
`create_reservation` at the same moment, reports status and time per
request, and deletes everything in `finally`. A session-level advisory lock
allows one run at a time. The same phase found the cause of a rare flaky
test run: two pytest processes truncating the shared test database; the
conftest now holds a session advisory lock.

**Alternatives considered.** Filtering names in JavaScript (the data would
still reach the browser); a fake race (sequential calls) in the Race Lab —
it would prove nothing.

**Where.** `schedule_service.py:board`, `services/race_lab.py`,
`routes/admin.py`, `static/app.js` (board, Race Lab chart).

**Tested.** `test_board_racelab.py` (9), smoke steps 26–27.

## U9. Check-in, no-show release and fairness (→ 402)

**Problem.** Booked-but-unused rooms waste capacity; and "is the allocation
fair?" had no number.

**Design.** `requires_checkin` and `checkin_grace_minutes` (5–60) on
resources, `checked_in_at` and the `no_show` status on reservations. Check-in
locks the reservation row and is idempotent. The job releases confirmed,
unclaimed bookings after start + grace with `FOR UPDATE SKIP LOCKED OF
reservations` (a check-in in progress is skipped, not waited for), then
offers the rest of the slot to the waitlist. Reputation: no-shows in the last
30 days lower waitlist priority (5 points each) and allocation weight.
Fairness analytics per group, with **Jain's index**
J = (Σx)² / (n · Σx²) over booked hours (1 = perfectly equal, 1/n = one
person gets everything).

**Alternatives considered.** Cancelling no-shows (hides the reason, no
reputation); a hard ban after N no-shows (too harsh, and not explainable by
one number).

**Where.** Migration `e7a9c1b3d5f6`; `reservations.py:check_in`,
`jobs.py:release_no_shows`, `groups.py`, `analytics.py:fairness`.

**Tested.** `test_checkin_fairness.py` (8), e.g.
`test_job_releases_unclaimed_bookings_and_promotes_the_waitlist`,
`test_jain_index_on_hand_built_values`.

## U10. Documentation and test dates (402 tests)

**Problem.** Many tests booked fixed dates in 2027; one day those become
past dates and the suite fails for no reason.

**Design.** `tests/dates.py`: `FUTURE_MONDAY` = the first Monday at least
120 days from today, with `future_day(n)` / `future_utc(n, hour)`. Each
converted file maps its old anchor Monday to `FUTURE_MONDAY`, so weekdays and
the spacing between dates stay exactly the same. Pure unit tests where the
date matters (DST, property tests) and the analytics test (past data
inserted directly) keep fixed dates. Demo data now feeds every analytics
section.

**Alternatives considered.** Freezing time with a library (a new dependency,
and PostgreSQL's `now()` would not be frozen).

**Where.** `tests/dates.py`, `scripts/seed_demo.py`.

**Tested.** The whole suite (402 passed).

---

## Viva Q&A

**1. Why not a Python lock around the booking code?**
It only works inside one process. With two uvicorn workers or two servers,
each has its own lock and both can insert. The database is the one place all
processes share, so the guarantee lives there.

**2. What is an exclusion constraint?**
A generalisation of UNIQUE: "no two rows may have values that all match the
given operators". Ours says "no two active rows with the same `resource_id`
(`=`) and overlapping time ranges (`&&`)". PostgreSQL checks it atomically
using a GiST index.

**3. Why do you need `btree_gist`?**
GiST indexes support range operators like `&&` but not plain `=` on integers.
`btree_gist` adds `=` support to GiST, so one index can combine
`resource_id =` with `tstzrange &&`.

**4. Why is `exclusive` a column instead of reading `resources.capacity`?**
A constraint's `WHERE` can only see the row itself. We stamp
`exclusive = is_exclusive(resource)` (capacity 1 or booking mode `whole`)
on each reservation when it is inserted, and refuse capacity or mode edits
that would make existing future flags wrong.

**5. How is capacity > 1 enforced then?**
The booking locks the resource row `FOR UPDATE`, computes the peak number of
simultaneous bookings in the range with a sweep line, and refuses if
`peak + party_size > capacity` (the weighted sweep line: each booking
counts its party size). Competing bookings for that resource wait for the
lock.

**6. Why FOR SHARE for exclusive (capacity-1 or whole) resources?**
The exclusion constraint already decides between competing bookings, so they
don't need to queue. But a blackout or resource edit takes `FOR UPDATE`, which
conflicts with `FOR SHARE`, so it waits until the booking has committed —
it can't be inserted between our blackout check and our insert.

**7. Why never upgrade a SHARE lock to UPDATE?**
If two transactions both hold SHARE and both try to upgrade, each waits for
the other: a deadlock. So we choose the right lock up front.

**8. What happens if two admins approve the same reservation at once?**
Both go through `_apply_status_change`, which locks the reservation row
`FOR UPDATE`. The second waits, then re-reads the status (`confirmed`); the
transition confirmed → confirmed is not allowed, so it gets 409.

**9. What if an admin approves while the member cancels?**
Same row lock: whichever comes second sees the new status. If the cancel won,
approve gets 409; if approve won, the cancel (confirmed → cancelled) is still
valid.

**10. Why are emails sent after commit?**
So we never email about a change that is rolled back, and never hold row locks
while waiting for a mail server. Emails are queued on the session and sent by
an `after_commit` listener in a background thread.

**11. How does SKIP LOCKED differ from NOWAIT?**
Both avoid waiting for a locked row. `NOWAIT` raises an error immediately;
`SKIP LOCKED` silently leaves the locked rows out of the result. For a job
that processes "whatever is free right now", skipping is what we want.

**12. What is a savepoint and why do series need it?**
A savepoint is a marker inside a transaction you can roll back to without
losing earlier work. In PostgreSQL a failed statement aborts the whole
transaction; with a savepoint per occurrence, a conflicting week is undone
alone and the transaction continues.

**13. How does the suggestion score work?**
Lower is better: one point per minute from the preferred time, 60 per day
later, 30 × the fraction of empty seats, plus 30 for each leftover gap too
short to be bookable and −15 for a snug fit. Ties are broken by start time and
resource id so results are deterministic.

**14. What is the time complexity of the sweep line?**
O(n log n) for sorting the 2n start/end events, then O(n) to scan them.

**15. How does the app behave with 2 workers?**
Correctness is unchanged: constraints and row locks live in PostgreSQL. Jobs
run once per tick (advisory lock). Each worker has its own LISTEN connection,
so SSE clients on either worker get every committed change. Only the in-memory
parts are per worker: rate limits and the job status counters.

**16. Why does each worker have its own LISTEN connection?**
SSE clients are connected to one specific worker process, so each worker must
hear every notification itself. PostgreSQL delivers each NOTIFY to all
listening connections.

**17. Can a member see who booked a slot through `/events`?**
No. Members receive only `{resource_id, kind}` (`member_view`), never
reservation ids, statuses or user ids.

**18. Why does promotion run outside the cancel transaction?**
To keep one lock order. Cancel holds a reservation lock; promotion needs
user → resource locks. Doing both in one transaction could deadlock with a
blackout (resource → reservations). Running promotion after the commit avoids
that, and a promotion error can't undo the cancel.

**19. How do you prevent the same waitlist entry being promoted twice?**
Entries are selected `FOR UPDATE SKIP LOCKED`, so two concurrent promotions
get disjoint entries; once an entry is committed as `promoted`, the
`status = 'waiting'` filter excludes it.

**20. Why a state machine for statuses?**
So illegal moves (approving a cancelled booking, cancelling a rejected one)
are impossible from any code path, and every change is recorded in one place
with an audit event.

**21. What is the audit trail used for?**
`reservation_events` gives the full history (`/reservations/{id}/history`),
the rejection reason shown to the member, and approval-latency analytics.

**22. Why are statuses defined as a whitelist (`IN ('pending','confirmed')`)?**
Earlier the app used `!= cancelled` while the constraints also excluded
`rejected`; the two drifted apart and rejected bookings blocked slots. With a
whitelist, a new status (like `expired`) is inactive everywhere unless it is
deliberately added.

**23. How do recurring bookings handle daylight saving time?**
Occurrences are built from the local date + local start time in the
resource's timezone and only then converted to UTC, so the local time stays
the same while the UTC time shifts.

**24. Why does the benchmark sleep in the naive version?**
Only to widen the race window so the bug is visible on a fast laptop. The race
exists without the sleep; it just happens less often.

**25. What would you change for production scale?**
Redis-backed rate limiting, a shared store for job status, several database
replicas, pagination on every list endpoint, and a real email queue with
retries.

### Upgrade questions

**26. How do you prevent deadlocks when a bundle locks several resources?**
Every transaction that locks more than one resource locks them in
**ascending id order** (after the user row). Two bundles over {A, B} and
{B, A} then both try A first; one waits, none holds what the other needs. A
deadlock needs a cycle in the wait-for graph, and a global order makes a
cycle impossible. A negative control during development (ordering
removed, two unit pools) made PostgreSQL report a deadlock; with the
ordering, the test runs both orders in parallel and sees none.

**27. What is the global lock order in this project?**
User → resource(s) in id order → reservations in id order. Blackouts and
pre-emption: resource → reservations. Allocation commit: round → users by id
→ resources by id. Anything that would need a different order (promotion,
re-accommodation, emails) runs after the commit in its own transaction.

**28. What is the weighted sweep line?**
Each booking becomes two events: `+party_size` at its start and
`−party_size` at its end. Sort by (time, delta) so ends come before starts at
the same instant, and keep a running sum: its maximum over the requested
range is the peak load. A new party of p fits if `peak + p ≤ capacity`.
O(n log n). With all weights 1 it is the original count-based sweep line.

**29. Why must ends be processed before starts at the same instant?**
Intervals are half-open `[start, end)`. A 9–10 booking and a 10–11 booking
never use the room at the same moment; if the start came first, the sweep
would briefly count both and wrongly report the room as full.

**30. Why is `preempted` inactive automatically?**
Both exclusion constraints and every query use the whitelist
`status IN ('pending', 'confirmed')`. Any new status is outside that list,
so a pre-empted booking stops blocking the slot, quota and capacity the
moment its status changes — no constraint had to be rewritten. The same is
true for `no_show`.

**31. What is starvation and how does aging prevent it?**
With strict priority, a steady stream of Faculty entries would keep a
Student waiting forever. Aging adds `WAITLIST_AGING_POINTS_PER_HOUR` per hour
waited to the effective priority, so every waiting entry eventually reaches
the top: with the defaults a Student (10) who waited 41 hours beats a
Faculty member (50) who just joined.

**32. Why is the waitlist order defined in one SQL expression?**
`waitlist_order()` is used both to promote and to show "your position". If
they were computed separately (SQL vs Python) they could disagree, and a
member would see position 1 but not be promoted first.

**33. What makes a pre-emption safe?**
One transaction locks requester → resource FOR UPDATE → all overlapping
reservations FOR UPDATE by id, then checks every victim (lower priority, 24 h
notice, not a bundle item, exclusive resource). If any one is protected,
nothing changes (409 with the reasons). New bookings can't slip in because
bookings of an exclusive resource hold FOR SHARE, which conflicts with our
FOR UPDATE.

**34. Why does re-accommodation run after the commit?**
It needs other locks (the victim's user, possibly another resource) in the
normal booking order. Doing it inside the pre-emption would break the lock
order and risk deadlock, and a failure in it would roll back the
pre-emption. After the commit, each victim gets its own transaction and a
failure only means "put them on the waitlist".

**35. Why can't you pre-empt bookings on a unit pool?**
A pool booking only uses some units. To make room the engine would have to
choose *which* of several overlapping bookings to bump (a small optimisation
problem of its own); we kept pre-emption to exclusive resources, where the
victims are exactly the overlapping bookings.

**36. How does the interval intersection for common slots work?**
Each list of free windows is sorted and non-overlapping. Two lists are
merged with two pointers: the overlap of the current windows is
`[max(starts), min(ends))` if non-empty; then the pointer whose window ends
first advances. Folding k lists pairwise is linear in the total number of
windows.

**37. Why is the general allocation problem NP-hard?**
Each request picks one of several (resource, time) placements, placements
conflict pairwise, and we maximise total weight: that contains weighted
interval scheduling on several machines with alternative intervals, and in
general maximum weight independent set in the conflict graph — NP-hard. So
no known algorithm is fast on every instance; we use an exact search with
limits and good heuristics.

**38. Why can greedy be suboptimal? Give an example.**
Greedy decides once and never revisits. In the demo round a Faculty member
can use 9, 10 or 11 o'clock and prefers 9; a Student can only come at 9.
Greedy serves Faculty first at 9 and the Student is left out. The optimal
solution moves Faculty to another hour and serves both (greedy 9 / 12,
optimal 11 / 12).

**39. How does branch-and-bound prune?**
At each node it computes an **optimistic bound**: the value so far plus the
best the remaining requests could possibly add. If that is not better than
the best complete solution found so far (the incumbent), the whole subtree is
cut. Because the bound never underestimates, pruning never loses a better
solution.

**40. What is forward checking in your solver?**
The second, tighter bound: for each remaining request, only the placements
that are *still feasible* given the current partial assignment count (the
first feasible one in cost order is its best). Later choices can only remove
options, so the bound stays optimistic, but it cuts about 4× more of the tree
than the cheap bound.

**41. Why warm-start branch-and-bound with greedy / local search?**
A good incumbent from the start makes the pruning test
`bound ≤ best` succeed much earlier. It also guarantees that, even if the
time limit stops the search, the result is never worse than the heuristics.

**42. What does `optimal = true` mean, and when is it false?**
True only if the search explored (or pruned) the whole tree within both the
node limit (200 000) and the time limit (2 s). Otherwise it returns the best
solution found and says `optimal = false` — never a false claim of
optimality.

**43. Why the objective Σ(1000 × weight − cost)?**
Cost is at most 100 and weight at least 1, so allocating one more request
(+1000 × weight) always beats any cost saving: the solver first maximises who
gets served (weighted by priority), and only then how close the placements
are to what was asked.

**44. What is local search doing, and what is an ejection chain?**
Hill climbing from greedy: (a) move an allocated request to a cheaper
placement; (b) an unallocated request wants a placement blocked by exactly
one allocated request — move that blocker elsewhere and give the slot to the
waiting one. Apply only strict improvements; stop at a local optimum.

**45. What is Jain's fairness index?**
J = (Σxᵢ)² / (n · Σxᵢ²) over what each member got (booked hours). It is 1
when everyone gets the same and 1/n when one person gets everything; members
with nothing count as 0. It is scale-free, so it compares groups of
different sizes.

**46. How does the commit of a round stay consistent if a slot was taken after solving?**
Commit locks the round, the users (by id) and the resources (by id), then
books each allocation inside its own SAVEPOINT through the normal booking
function. If one slot was taken meanwhile, only that savepoint rolls back
and the request is marked "taken after solving"; the rest commit.

**47. How does the Race Lab make the requests truly simultaneous?**
Each of N threads opens its own database session and waits at a
`threading.Barrier(N)`; the barrier releases all of them at once, and they
call the real `create_reservation`. The database (exclusion constraint for
whole rooms, row lock + weighted sweep line for pools) decides the winners.

**48. Why can't the no-show job and a check-in race each other?**
Check-in locks the reservation row. The job selects candidates
`FOR UPDATE SKIP LOCKED OF reservations`: a row being checked in right now is
skipped and re-examined on the next tick, after the check-in has committed —
then it is no longer "unclaimed".

**49. How do members see the board without seeing who booked?**
The server builds two different payloads. Members get their own bookings
plus `{start, end, busy: true}` for everyone else's (and the unit load for
pools) — no names, user ids, reservation ids or statuses ever leave the
server. The test checks the raw response text for the other user's name and
email.

**50. Why did the tests need relative dates?**
Bookings in the past are refused (correctly). Tests that booked fixed 2027
dates would all start failing once 2027 arrives. `tests/dates.py` always
returns dates at least 120 days ahead, and keeps weekdays the same, so the
tests mean exactly what they meant before.
