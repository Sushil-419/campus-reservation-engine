# Viva cheat sheet (one page)

## The problem statement in 5 lines

1. **Multi-user** — approved accounts in groups (Student 10 / Staff 30 / Faculty 50) with their own quota, horizon, max length, restricted resources.
2. **Resource** — whole rooms (one booking at a time) or unit pools (party sizes add up), opening hours, blackouts, check-in.
3. **Reservation** — 7-status state machine (pending, confirmed, cancelled, rejected, expired, preempted, no_show) with an audit trail; series and all-or-nothing bundles.
4. **Scheduling** — ranked suggestions, common free slots (interval intersection), priority waitlist with aging, pre-emption with re-accommodation, allocation rounds (greedy / local search / branch-and-bound).
5. **Engine** — correctness lives in PostgreSQL: EXCLUDE constraints, row locks in one global order, savepoints, advisory locks, SKIP LOCKED — proven live by the Race Lab.

## The 12 most likely examiner questions

**1. What is the exclusion constraint?**
`EXCLUDE USING gist (resource_id WITH =, tstzrange(start,end) WITH &&) WHERE active AND exclusive`: no two active rows of the same exclusive resource may overlap. PostgreSQL checks it atomically on every insert (SQLSTATE 23P01 → 409); `btree_gist` lets one GiST index mix `=` and `&&`.

**2. What is your lock order and why?**
User → resource(s) by ascending id → reservations by id (blackouts / pre-emption: resource → reservations; round commit: round → users → resources). One global order means no wait-for cycle, so no deadlock; anything needing other locks runs after the commit.

**3. FOR SHARE vs FOR UPDATE?**
Exclusive resources: FOR SHARE — bookings proceed in parallel (the constraint picks the winner) but a blackout/edit (FOR UPDATE) must wait. Unit pools: FOR UPDATE — the peak check must be serialised. Never upgrade SHARE → UPDATE (two upgraders deadlock).

**4. What does SKIP LOCKED do here?**
`SELECT … FOR UPDATE SKIP LOCKED` returns only rows nobody holds. The job (expiry, no-show release) and promotion skip a row someone is editing right now and retry next tick, instead of waiting or double-processing.

**5. What is a savepoint and where do you use it?**
A rollback point inside a transaction. A failed statement aborts a PostgreSQL transaction, so series occurrences, waitlist promotions and round commits each get a SAVEPOINT: one conflict undoes only that item.

**6. What is the weighted sweep line?**
Events `+party` at each start, `−party` at each end, sorted by (time, delta) so ends come first at equal times; the running sum's maximum is the peak load. A party fits if `peak + party ≤ capacity`. O(n log n).

**7. What is aging and why do you need it?**
Effective priority = group priority + 1 point per hour waited − 5 per recent no-show (≥ 0). Without aging a Student could starve behind a stream of Faculty; with it a Student who waited 41 h beats fresh Faculty. One SQL expression orders both promotion and "your position".

**8. Why is pre-emption safe?**
One transaction locks requester → resource FOR UPDATE → overlapping bookings by id, re-checks every victim (lower priority, ≥ 24 h notice, not a bundle item, exclusive resource); one protected victim → nothing changes. `preempted` is outside the active whitelist, so the slot frees instantly. Re-accommodation runs after the commit, one victim per transaction.

**9. How do you prevent deadlocks between bundles?**
Lock the user, then every resource in ascending id order. Bundles {A,B} and {B,A} both lock A first → one simply waits. The test runs both orders in parallel; without ordering PostgreSQL reported a deadlock.

**10. Greedy vs branch-and-bound?**
Greedy: heaviest request first takes its cheapest feasible placement — fast, never revisits, can be suboptimal (demo round: 9/12 vs 11/12). B&B: depth-first over "which placement or none", prunes when an optimistic bound ≤ the best found, warm-started with greedy/local search; proven optimal if it finishes within 200 000 nodes / 2 s. The problem is NP-hard, hence the limits.

**11. What is forward checking?**
A tighter bound in B&B: each remaining request counts only its best placement that is *still feasible* given the current choices. Still optimistic (choices only remove options), so pruning stays safe; ~4× fewer nodes.

**12. What is Jain's fairness index?**
J = (Σx)² / (n·Σx²) over booked hours per member: 1 = everyone equal, 1/n = one person has everything. Reported overall and per group; demo data ≈ 0.96.

## Key numbers

| What | Number |
|---|---|
| Automated tests | **402 passed** (29 files; 47 pure unit, 12 Hypothesis properties) |
| E2E browser test | 27/27 steps |
| Race scripts | 20 parallel → 1; 20 by one user → 5 (quota); capacity 3 → 3 |
| Benchmark (50 threads × 5) | naive **198 double bookings**; engine 0 (B: [1,1,1,1,1], C: [5,5,5,5,5]) |
| Unrelated bookings in parallel | D: 50 bookings 175 ms/round vs B (1 booking) 158 ms |
| Race Lab | 20 → **1 winner** (whole); pool of 3 → **3**; pool of 10 (25 requests) → **10** |
| Allocator (seed 7) | 10 req: all solvers 5/10, B&B proven in 97 nodes, 1.8 ms; 40 req: greedy 13, local 15, B&B **16**; 80 req: 18 / 18 / **20** |
| Demo round | greedy 9/12, local search 11, optimal 11 (proven, 120 nodes, 2.4 ms) |
| Schema | 14 tables, 11 enums, 2 EXCLUDE, 27 CHECK, 25 migrations (all with downgrade) |
| API | 76 endpoints + 7 pages |

## Who explains what

| Topic | Team member |
|---|---|
| Problem, architecture, database guarantees (constraints, locks, Race Lab) | ____________ |
| Capacity models, sweep line, suggestions, common slots, bundles | ____________ |
| Groups, priority waitlist with aging, pre-emption, check-in / no-shows | ____________ |
| Allocation rounds: greedy, local search, branch-and-bound, Jain's index | ____________ |
| Frontend (board, tabs), testing, benchmarks, demo | ____________ |
