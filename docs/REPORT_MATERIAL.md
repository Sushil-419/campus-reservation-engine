# Report material

Text and figures for the college project report. All numbers come from runs
made on 2026-10-06 (see "Testing summary" and "Results").

## Abstract

Shared resources such as meeting rooms, laboratories and equipment are often
booked through spreadsheets or simple forms, which leads to double bookings,
unclear approval, unfair access and poor use of capacity. This project builds
a *Multi-User Resource Reservation and Scheduling Engine*: a web application
in which members of different user groups (students, staff, faculty) book
resources, administrators approve bookings and manage resources, and the
system itself guarantees that no slot is ever over-booked. The backend is
written in Python with FastAPI and uses PostgreSQL as the single source of
truth. Correctness is enforced inside the database with exclusion
constraints, row-level locks taken in one global order, savepoints and
advisory locks, so it holds with many simultaneous requests and several
server processes. On this core the engine models two capacity types (whole
rooms and pools of units, checked with a weighted sweep line), group
priorities with per-group policies, pre-emption by higher-priority groups
with automatic re-accommodation of the displaced users, all-or-nothing
bundles of several resources found by interval intersection, a priority
waitlist with aging that prevents starvation, check-in with release of
no-shows, and **allocation rounds** that assign many competing requests at
once with three algorithms — greedy, local search and an exact
branch-and-bound with forward checking — whose results can be compared side
by side. Live updates, emails, calendar export, a resource board and an
analytics dashboard with fairness metrics (Jain's index) complete the
system. It is verified by 402 automated tests (including property-based
tests against brute-force oracles), three live concurrency scripts, a
27-step browser test, an in-app "Race Lab" in which 20 truly simultaneous
requests produce exactly one winner, and a benchmark in which a naive
implementation made 198 double bookings in 5 rounds while the engine made
none.

## Objectives

1. Let multiple users in different groups book shared resources through a web interface, with group-specific rights (priority, quota, booking horizon, maximum length, restricted resources).
2. Guarantee, under concurrent load, that a resource is never over-booked — for whole rooms and for pools of units — and that a user never double-books.
3. Model resource policies: opening hours, weekdays, durations, capacity and capacity model, timezone, maintenance blackouts and check-in.
4. Provide a clear reservation lifecycle (pending, confirmed, cancelled, rejected, expired, preempted, no_show) with approval and a full audit trail.
5. Let higher-priority users take a slot when it matters, without leaving the displaced user stranded (pre-emption with re-accommodation).
6. Book several resources (and find a time when several people are free) atomically.
7. Allocate many competing requests at once as well as possible, compare algorithms, and explain every decision.
8. Keep access fair over time: priority with aging, a reputation for no-shows, and fairness metrics.
9. Prove correctness with automated tests, live concurrency demonstrations and benchmarks.

## Scope

**In scope:** accounts with admin approval, one admin role, user groups and
priorities, resources with policies and two capacity models, single,
recurring and bundled bookings, pre-emption, waitlist with aging,
allocation rounds with three solvers, check-in and no-shows, background
jobs, real-time updates, email and calendar, resource board, Race Lab,
analytics with fairness, a project-specific chatbot, Docker setup.

**Out of scope:** payments, multiple organisations, pre-emption on unit
pools, physical check-in (QR codes, sensors), mobile apps, high-availability
deployment.

## Module-wise description

**Authentication, users and groups.** Users sign up with email and password
(bcrypt) or Google OAuth, verify their email (case-insensitive and unique),
and wait for admin approval, at which point the admin chooses their group.
Groups (Student, Staff, Faculty, or new ones) carry a priority, a quota, a
booking horizon, a maximum booking length and whether they may pre-empt.
Sessions are random tokens in the database sent as httpOnly cookies.
Denying a member revokes their sessions and releases all their bookings.

**Resource management.** Admins create resources with capacity, a capacity
model (`whole`: one booking at a time, capacity = most people; `units`: a
pool of units shared by overlapping bookings), timezone, opening hours, open
weekdays, duration limits, auto-approve, check-in and allowed groups. Edits
are locked and validated so they never invalidate existing future bookings.
Maintenance blackouts block time; with "force" they cancel conflicting
bookings in the same transaction.

**Reservation core.** A booking is validated against global limits, the
resource policy and the member's group, then inserted under the user lock
and one resource lock (shared for exclusive resources, exclusive for pools);
for pools the weighted peak is checked, and the database's exclusion
constraints reject any overlap on exclusive resources. All status changes go
through a state machine with row locking and an audit event.

**Pre-emption.** A Faculty booking with `preempt=true` on an occupied
exclusive slot locks the resource and the overlapping bookings and checks
every victim (lower priority, at least 24 hours away, not part of a bundle).
Victims become `preempted`; after the commit each is moved to the best
alternative on the same day, or put on the waitlist, and informed by email.

**Bundles and common slots.** Common free slots are the intersection of the
free windows of every resource (with room for each party) and every
participant's free time. A bundle books all its resources in one
transaction, locking them in ascending id order so two bundles can never
deadlock.

**Scheduling engine.** Pure functions compute an occupancy profile with a
(weighted) sweep line, derive free windows, subtract blocked time, intersect
window lists, generate clock-aligned candidates and score them on closeness
to the preferred time, day offset, wasted capacity and fragmentation. The
same engine supplies alternatives when a booking fails.

**Recurring series.** Daily or weekly rules are expanded in the resource's
timezone (DST-safe), at most 26 occurrences and 90 days, previewed per
occurrence and booked with one savepoint per occurrence (all-or-nothing or
skip-conflicts). A series counts as one booking toward the quota.

**Waitlist.** Members wait for a full slot. When capacity frees up, a
separate transaction promotes waiting members by effective priority (group
priority + aging − no-show penalty), respecting quota and policies, never
promoting the same entry twice.

**Allocation rounds.** The admin opens a round with a window and a deadline;
members submit requests with several acceptable windows. After the deadline
the round is solved by greedy, local search or branch-and-bound (or all
three, compared), and committed in one transaction with a savepoint per
booking; every request left out gets an explanation.

**Check-in and fairness.** On check-in resources the owner must check in
between 10 minutes before the start and the end of the grace period; the job
releases unclaimed bookings, frees the slot for the waitlist and records a
no-show, which lowers the member's priority for 30 days. Analytics report
per-group fairness and Jain's index.

**Background jobs.** A loop inside the application closes due allocation
rounds, expires unapproved bookings, releases no-shows, cleans expired
sessions and tokens and runs promotion as a safety net. A PostgreSQL
advisory lock ensures one runner per tick; `SKIP LOCKED` avoids waiting on
rows being edited.

**Real-time updates, notifications, calendar.** Every committed change
publishes a PostgreSQL NOTIFY; each server process forwards it to browsers
over Server-Sent Events. Emails are queued during the transaction and sent
only after it commits. Reservations can be exported as iCalendar files and
subscribed to as a private feed.

**Resource board and Race Lab.** The board shows all resources against time
(day or week): admins see every booking and can approve from it; members see
their own and anonymous busy blocks. The Race Lab fires N truly simultaneous
real bookings at a sandbox resource and shows that exactly the allowed
number win.

**Analytics.** Status counts, utilization, a 7×24 heatmap in local time,
approval latency, waitlist statistics, pre-emptions and re-accommodation
rate, top users, fairness per group with Jain's index, no-show rates and a
CSV export.

**Assistant.** A Groq-powered chatbot answers questions about the project
only; unrelated or sensitive questions are refused before the model is
called.

## Key algorithms (pseudo-code)

### Weighted peak (sweep line)

```
function WEIGHTED_PEAK(bookings, start, end):
    events ← []
    for b in bookings:                              # active bookings only
        if b.start < end and b.end > start:
            events.append((max(b.start, start), +b.party_size))
            events.append((min(b.end, end),   −b.party_size))
    sort events by (time, delta)       # at equal times ends (−) come before starts (+)
    load ← 0; peak ← 0
    for (t, delta) in events:
        load ← load + delta
        peak ← max(peak, load)
    return peak                         # O(n log n)

can_book(pool, party, start, end)  ⇔  WEIGHTED_PEAK(pool bookings, start, end) + party ≤ pool.capacity
```
For an exclusive resource (capacity 1 or `whole`) the database's `no_overlap`
exclusion constraint decides instead, and the party only has to fit the
room's capacity.

### Priority with aging (waitlist order)

```
function EFFECTIVE_PRIORITY(entry, now):
    hours  ← (now − entry.created_at) in hours
    shows  ← number of entry.user's no-shows in the last NO_SHOW_WINDOW_DAYS
    return max(0, group(entry.user).priority
                  + AGING_POINTS_PER_HOUR × hours
                  − NO_SHOW_PENALTY_POINTS × shows)

function PROMOTE(resource, start, end):         # own transaction, after the freeing commit
    entries ← waiting entries of resource overlapping [start, end) in the future,
              ORDER BY EFFECTIVE_PRIORITY desc, created_at, id   FOR UPDATE SKIP LOCKED
    lock the entries' users FOR UPDATE in id order; lock the resource
    for e in entries:
        if e.user over quota or group lost access: continue
        SAVEPOINT
        try:   book e's slot for e.party_size (normal checks); e.status ← promoted
        except conflict: ROLLBACK TO SAVEPOINT    # still full: stays waiting
    COMMIT
```
The same ORDER BY gives every member their position, so the shown position
and the real order can never disagree.

### Pre-emption

```
function PREEMPT(requester, resource, start, end, party):
    BEGIN
    lock requester's user row FOR UPDATE
    lock resource FOR UPDATE
    victims ← active reservations of resource overlapping [start, end)
              ORDER BY id FOR UPDATE
    if not group(requester).can_preempt:                          → 403
    for v in victims:
        refuse if v.bundle_id ≠ null or v.user = requester
               or not exclusive(resource)
               or priority(group(v.user)) ≥ priority(group(requester))
               or v.start < now + PREEMPTION_MIN_NOTICE_HOURS
    if any refusal: ROLLBACK, 409 with the reasons                 # all or nothing
    for v in victims: v.status ← preempted; v.preempted_by ← new booking (event + email)
    insert the requester's booking (normal policy, group and quota checks)
    COMMIT
    for v in victims:                                  # each in its own transaction
        for s in SUGGEST(same type, same day, v.party_size, preferred = v.start):
            try: book s for v.user with v's previous status; email; next victim
            except conflict: try the next suggestion
        if nothing booked: put v.user on the waitlist for v's original slot
```

### Interval intersection (common free slots)

```
function INTERSECT(lists):          # each list sorted and non-overlapping
    result ← lists[0]
    for other in lists[1:]:
        merged ← []; i ← 0; j ← 0
        while i < |result| and j < |other|:
            s ← max(result[i].start, other[j].start)
            e ← min(result[i].end,   other[j].end)
            if s < e: merged.append([s, e))
            if result[i].end < other[j].end: i ← i + 1 else: j ← j + 1
        result ← merged
    return result                    # O(k × total windows)

COMMON_SLOTS = candidates of INTERSECT(free windows of every resource with room for its party,
                                       free time of the requester and every participant)
               minus the past and the group's horizon, scored and ranked
```

### Greedy allocation

```
value(r, p) = 1000 × weight(r) − cost(p)        # cost 0..100, weight ≥ 1

function GREEDY(requests):
    order ← requests sorted by (weight desc, number of placements asc, id)
    chosen ← {}
    for r in order:
        for p in r.placements sorted by cost asc:
            if FEASIBLE(chosen + {r: p}):           # exclusive / units / one place per person / quota
                chosen[r] ← p; break
    return chosen                                   # never revisits a decision
```

### Branch-and-bound (exact)

```
function OPTIMAL(requests, node_limit, time_limit):
    best ← better of GREEDY and LOCAL_SEARCH          # warm start (incumbent)
    order ← as in GREEDY;  opts[i] ← placements of order[i] by cost asc
    suffix[i] ← Σ over k ≥ i of value(order[k], cheapest placement)
    DFS(0, {}, 0)
    return best, optimal = (search finished within both limits)

function DFS(i, chosen, current):
    if limits exceeded: stop the search
    if current + suffix[i] ≤ best.value: return                # cheap bound
    if i = |order|: best ← (chosen, current); return
    fc ← current + Σ over k ≥ i of value(order[k], first placement still FEASIBLE with chosen)
    if fc ≤ best.value: return                                 # forward-checking bound
    for p in opts[i]:
        if FEASIBLE(chosen + {order[i]: p}):
            DFS(i + 1, chosen + {order[i]: p}, current + value(order[i], p))
    DFS(i + 1, chosen, current)                                # leave order[i] unallocated
```
Both bounds are optimistic (never below the true best completion), so
pruning never discards a better solution.

### Local search

```
function LOCAL_SEARCH(start = GREEDY):
    repeat at most 50 rounds:
        if RELOCATE() or EJECT(): continue           # apply the first strictly improving move
        break                                        # local optimum
    return chosen

RELOCATE: for an allocated request r, a cheaper placement p that is feasible
          → move r to p
EJECT:    for an unallocated request r and a placement p blocked by exactly
          ONE allocated request b: if b can move to another feasible
          placement q and value(r,p) + value(b,q) − value(b,old) > 0
          → move b to q, give p to r
```

### Free-slot suggestion and scoring

```
function SUGGEST(resources, duration, dates, preferred_time, attendees, user):
    results ← []
    for r in resources with r.active, bookable by user's group, room for attendees:
        load bookings and blackouts of r for the whole date range   # 2 queries
        for day in dates where day is an open weekday of r and within the group's horizon:
            window  ← [open_time, close_time] of day in r.timezone, as UTC
            profile ← OCCUPANCY_PROFILE(bookings weighted by party, window)
            free    ← windows with enough room (whole: empty; units: attendees units left)
            free    ← free − blackouts − [−∞, now] − user's own bookings
            for start in times aligned to 15 min with [start, start+duration) ⊆ free:
                score ← 1.0·|start − preferred| (min) + 60·(day − first day)
                      + 30·(r.capacity − attendees)/r.capacity
                      + 30·(#leftover gaps shorter than r.min_duration)
                      − 15·(1 if flush against a window edge or booking)
                results.append((score, start, r.id))
    return the first N of results sorted by (score, start, resource_id)
```

## Database design summary

PostgreSQL 17 with fourteen tables: `user_groups`, `users`, `sessions`,
`email_tokens`, `resources`, `resource_allowed_groups`,
`resource_blackouts`, `reservations`, `reservation_events`,
`reservation_series`, `reservation_bundles`, `waitlist_entries`,
`allocation_rounds`, `allocation_requests`, and eleven enum types (for
example `reservation_status`: pending, confirmed, cancelled, rejected,
expired, preempted, no_show). The key integrity rules are two GiST
exclusion constraints on `reservations` (`no_overlap` for exclusive
resources, `no_user_duplicate_reservation` for everyone), 27 CHECK
constraints (intervals, opening hours, durations, weekday masks, series
rules, party sizes, series-or-bundle, check-in grace, group limits, round
windows, request windows), a unique index on `lower(email)` and a partial
unique index on waiting waitlist entries. All timestamps are `timestamptz`;
every database connection runs in UTC. The schema is managed by 25 Alembic
migrations, each with a working downgrade (the downgrades that remove an
enum value map it to the closest remaining status). The full diagram is in
`docs/ER_DIAGRAM.md`.

## Testing summary

| Kind | Count / result | Command |
|---|---|---|
| Automated tests (pytest) | **402 passed** in about 190 s, 29 test files | `pytest -q` |
| of which pure unit tests (no database) | 47 (scheduler 22, recurrence 10, allocator 15) | |
| of which property-based tests (Hypothesis) | 12 properties against brute-force oracles (interval code minute by minute; allocator by exhaustive search), plus 1 edge-case test | |
| of which concurrency tests inside pytest | parallel whole-room / unit bookings, opposite-order bundles, pre-emption vs cancel, approval vs deny, token consumption, job SKIP LOCKED, Race Lab | |
| Live concurrency scripts | 3/3 PASS: 20 parallel requests on one slot → exactly 1 succeeded; 20 parallel requests by one user → exactly 5 (the quota); 10 users on a capacity-3 resource → exactly 3 | `python tests/concurrency_test.py` etc. |
| Browser end-to-end test | **27/27 steps** passed, 0 console errors | `python tests/e2e/smoke_test.py` |
| All checks together | ALL CHECKS PASSED | `scripts/run_all_checks.sh` |

Tests that create bookings use dates relative to today (`tests/dates.py`),
so the suite does not age.

Code size (lines, `wc -l`): application Python 10,564; frontend
(HTML/CSS/JS) 8,375; tests 9,621; scripts 1,269.

Test count per upgrade phase: 204 (original) → 267 (hardening) → 297
(capacity models) → 317 (groups) → 333 (pre-emption) → 355 (bundles) → 370
(allocation engine) → 385 (allocation rounds) → 394 (board, Race Lab) → 402
(check-in, fairness).

## Results

### Naive vs engine

`python scripts/benchmark_naive_vs_engine.py` (50 threads, 5 rounds, the
naive version pauses 20 ms between check and insert to widen the race window):

| Scenario | Successes per round | Double bookings | p50 ms | p95 ms | Throughput req/s |
|---|---|---|---|---|---|
| A naive check-then-insert | [3, 50, 50, 50, 50] | 198 | 36.7 | 94.9 | 957.4 |
| B engine, capacity 1 | [1, 1, 1, 1, 1] | 0 | 145.4 | 165.0 | 316.7 |
| C engine, capacity 5 | [5, 5, 5, 5, 5] | 0 | 103.9 | 165.7 | 287.1 |
| D engine, 50 different resources | [50, 50, 50, 50, 50] | 0 | 165.2 | 188.3 | 285.8 |

The naive approach accepted almost every simultaneous request for the same
slot; the engine admitted exactly the capacity every time. Scenario D shows
that bookings on different resources do not block each other (50 successful
bookings in about the same wall time — 175.0 ms per round — as scenario B,
157.9 ms, where only one booking succeeds).

### Race Lab (in-app, real `create_reservation`, threads released by a barrier)

| Requests | Sandbox | Expected winners | Winners | Rejected (409) | Median ms | Max ms |
|---|---|---|---|---|---|---|
| 20 | whole room | 1 | **1** | 19 | 98.7 | 101.6 |
| 20 | pool of 3 units | 3 | **3** | 17 | 49.9 | 81.1 |
| 25 | whole room | 1 | **1** | 24 | 87.8 | 91.0 |
| 25 | pool of 10 units | 10 | **10** | 15 | 67.6 | 113.7 |

### Allocator benchmark

`python scripts/benchmark_allocator.py` (seed 7; the exact solver has a 2 s
and 200 000-node limit):

| Requests | Greedy allocated | Local search allocated | Optimal allocated | Optimal proven? | Optimal nodes | Optimal ms |
|---|---|---|---|---|---|---|
| 10 | 5/10 | 5/10 | 5/10 | yes | 97 | 1.8 |
| 20 | 11/20 | 12/20 | 12/20 (lower cost) | no (time limit) | 84 480 | 2000 |
| 40 | 13/40 | 15/40 | **16/40** | no (time limit) | 28 416 | 2016 |
| 80 | 18/80 | 18/80 | **20/80** | no (time limit) | 8 192 | 2053 |

Greedy and local search take well under 2 ms even for 80 requests; the
exact search is never worse than either (it starts from the better one) and
serves up to 2 more people on the larger instances. On the seeded demo
round (12 requests) greedy allocates 9, local search 11 and branch-and-bound
11 with a better objective, proven optimal in 120 nodes (2.4 ms).

### Demo data analytics (seeded database, last 30 days)

Pre-emptions 3, all re-accommodated (100 %); waitlist 4 entries, 3 promoted
(75 %); no-show rate on the check-in pod 6 / 33 (18 %); Jain's index over
all members 0.96 (Student 0.97, Staff 1.00, Faculty 0.99).

## Limitations and future scope

**Limitations:** rate limiting and job status are kept in memory per server
process; a single PostgreSQL instance; analytics ranges are whole UTC days;
the exact allocation solver has node and time limits (allocation is
NP-hard); pre-emption only on exclusive resources and re-accommodation only
on the same day; check-in is a button, not a physical check; the chatbot
relies on a keyword filter and an external API; emails go to the console
without SMTP configuration; administrators cannot book; quota and unit
capacity are enforced by locked application code rather than a constraint.

**Future scope:**
- **Integer programming or constraint programming** (e.g. OR-Tools) for very large allocation rounds, and multi-day / recurring requests inside rounds.
- **Pre-emption on unit pools**, choosing the cheapest set of bookings to displace.
- **QR-code or NFC check-in** at the door, and automatic release integrated with room sensors.
- **Fairness-aware allocation**: add Jain's index (or max-min fairness) to the objective, not only report it.
- **Redis-backed rate limiting and shared job status** for multi-instance deployments; horizontal scaling behind a load balancer (already safe thanks to database-level guarantees) and read replicas for analytics.
- **Reliable email delivery** with a persistent queue and retries; push notifications in a mobile-friendly progressive web app.
