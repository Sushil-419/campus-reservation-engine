# Live demo script (15 minutes)

The story: **open with the hard problem** (many people, one slot, the same
instant), show that the database solves it, then show what the engine builds
on that safe core — the board, groups and priorities, pre-emption, bundles,
allocation rounds — and finish with the numbers.

Commands are for **macOS / Linux** (`source ~/venvs/resvdb/bin/activate`,
or your own venv). On Windows use `venv\Scripts\activate` and `\` instead of
`/`.

## Before the audience arrives (10 minutes)

1. PostgreSQL is running and the dev database is migrated:
   ```bash
   alembic upgrade head
   ```
2. Load fresh demo data. This **deletes all reservations, resources, series,
   bundles, blackouts, waitlist entries and allocation rounds** in the dev
   database, plus the `@demo.local` users; real accounts (the admin) stay:
   ```bash
   python scripts/seed_demo.py --reset
   ```
   Check the summary: `round #… 12 requests; greedy would allocate 9,
   optimal 11`, `past pre-emptions (re-accommodated): 3`, `bundle: {'bundles': 1…}`.
3. Make sure a naive benchmark result exists (the Race Lab shows it):
   ```bash
   python scripts/benchmark_naive_vs_engine.py --quick
   ```
4. Start the server (terminal 1):
   ```bash
   uvicorn app.main:app --port 8050
   ```
5. Start the full test suite in **terminal 2** now (about 3 minutes, its own
   database, doesn't disturb the demo):
   ```bash
   python -m pytest -q
   ```
6. Open three browser windows (separate logins: a normal window, a private
   window, and a second browser or profile) at <http://127.0.0.1:8050>:

   | Window | Account | Group |
   |---|---|---|
   | A | the `ADMIN_EMAIL` account | admin |
   | B | `rohan@demo.local` / `demo1234` | Student (priority 10) |
   | C | `asha@demo.local` / `demo1234` | Faculty (priority 50, may pre-empt) |

   In window A, open **Admin** once so the Race Lab is loaded; in B and C
   switch to **Resource board**.

> If a demo member gets "booking limit reached" (409), they already hold
> their group's quota of active bookings from the seed — use another member
> of the same group (Students: `neha`, `vikram`, `kiran`…; Faculty: `ravi`).

---

## The demo

| # | Time | Step | What the audience should see |
|---|---|---|---|
| 1 | 0:00 | One sentence: "Many people book shared rooms at the same moment; the **database** guarantees nobody gets the same slot — let me prove it live." | – |
| 2 | 0:30 | **Race Lab (window A → Admin → Race Lab).** Slider 20, *Whole room*, **Run**. | Verdict: **1 winner, 19 rejected** — "decided by the GiST exclusion constraint". 20 tiles (one green), the latency chart in finish order, and under it the saved naive benchmark (dozens of double bookings for the same race). Say: "20 threads released by a barrier, the real booking code, not a simulation." |
| 3 | 1:45 | Switch to *Pool of units*, capacity 3, **Run**. | **Exactly 3 winners**, 17 rejected — "decided by the FOR UPDATE row lock and the weighted sweep line". Explain in one line why pools need a lock (a constraint can't add up party sizes). |
| 4 | 2:45 | **Resource board (window A, then B).** Day view, then **Week**. | Admin: every resource as a row, names and party sizes, the Projector Cart / Computer Lab load strips ("2/30"), the blackout hatched, closed hours grey. Click a pending block → popover → **Approve**. Window B (Student): the same board but other people's bookings are just "busy"; the 3D Printer (Staff/Faculty only) is not listed. |
| 5 | 4:00 | **Groups and priorities (window A → Admin → User groups).** | Student 10 / Staff 30 / Faculty 50 ("may pre-empt"), Students limited to 14 days ahead. In window B the header line shows *Student · n/5 bookings · up to 14 days ahead* (plus the no-show penalty if Rohan has one). Mention aging: "a Student who waited 41 h overtakes a fresh Faculty entry — no starvation." |
| 6 | 5:00 | **Pre-emption.** Window B (Student Rohan): book **Conference Room B** in 2 days, 15:00–16:00. Window C (Faculty Asha): try the same slot. | Window C: 409 plus **"Book anyway — bump 1 lower-priority booking"** → **Yes, bump and book** → "1 moved to an alternative, 0 put on the waitlist". Window B updates live: *"Taken by a higher-priority booking — moved to …"* (a same-day alternative, same status). |
| 7 | 6:30 | Explain safety in two lines: one transaction locks user → resource → the overlapping bookings by id; every victim must be lower priority and ≥ 24 h away, else nothing changes; re-accommodation runs **after** the commit. | – |
| 8 | 7:00 | **Bundle through common slots (window C or another member → Find a slot → Several resources together).** Pick *Seminar Hall* + *Projector Cart*, party 10, 120 min, the next 5 days → **Find slots**. | Ranked common slots with the remaining units per resource. **Book all** → confirm → "Bundle booked" — both items appear together in *My reservations* as one bundle. Say: "intersection of free windows; all or nothing; resources locked in ascending id so two bundles can't deadlock." |
| 9 | 8:30 | **Allocation round (window A → Allocation tab).** Open the seeded round *Lab sessions, week of …* (12 requests). **Close**, then **Compare all**. | Table: greedy 9/12, local search 11/12, optimal **11/12, proven optimal** (~100 nodes, a few ms), with objective, cost and Jain's index. Explain the trap: a priority member who could take any of three hours but prefers the first; greedy gives it to them and leaves a Student out, the optimal solver moves them. |
| 10 | 10:00 | Choose **Optimal**, **Solve**, then **Commit**. In window B open the **Allocation** tab. | Lanes per resource with the proposal; after commit the round is *committed*; the member sees *allocated* with the booked time, or a plain-language explanation if left out. |
| 11 | 11:00 | **Analytics (window A → Analytics, default range).** | KPI tiles, utilization bars, heatmap; **Pre-emptions: 3 · 3 re-accommodated (100 %)** (+1 from step 6 if in range); waitlist promotion rate; **Fairness**: per-group table with Jain's index, pre-emptions made / suffered; **no-show rate** of Focus Pod 1 (~18 %). |
| 12 | 12:30 | **Terminal 2:** the finished pytest run. Optionally `python tests/concurrency_test.py` (20 real HTTP requests → 1 winner). | `402 passed`. |
| 13 | 13:15 | Close: "Correctness lives in the database, so it holds for any number of workers; everything else — priorities, pre-emption, bundles, optimal allocation — is built on top of that guarantee." | Questions. |

---

## Backup plan (per step)

| Step | If this happens | Do this |
|---|---|---|
| Any | Server won't start | Check PostgreSQL is running and `DATABASE_URL` in `.env`; run `alembic upgrade head`. |
| Any | Demo member login fails | Re-run `python scripts/seed_demo.py --reset` (recreates the members, password `demo1234`). |
| 2–3 Race Lab | "Race Lab is disabled" (404) | `RACE_LAB_ENABLED` is false in `.env`; remove the line and restart. |
| 2–3 Race Lab | "already in progress" (409) | Another run is still finishing; wait two seconds and press Run again. |
| 2 Race Lab | No benchmark line under the chart | Run `python scripts/benchmark_naive_vs_engine.py --quick` in a terminal and show its table instead (A naive has double bookings, B is exactly 1). |
| 2–3 Race Lab | Anything else | Run `python tests/concurrency_test.py` live (20 HTTP requests → exactly 1 winner), or show `screenshots/board/race_lab_light.png`. |
| 4 Board | Board empty / "No resources" | Pick a weekday with the date picker (some resources are closed on Sundays); reload. Fallback: `screenshots/board/admin_day_light.png`, `member_day_light.png`. |
| 5 Groups | Group list collapsed | Click the **User groups** heading (admin sections are collapsible). |
| 6 Pre-emption | No "Book anyway" button | The booking must be ≥ 24 h away, on a whole room, and the bumper must be Faculty: check the slot is 2+ days ahead and window C is a Faculty member. |
| 6 Pre-emption | Asha hits her quota | Use `ravi@demo.local` (also Faculty). |
| 6 Pre-emption | Window B doesn't update | Check "● Live" in the header; otherwise reload — the move is already in the database. |
| 8 Bundle | No common slots | Widen the date range or reduce the party; the cart may be blacked out on one day (the seeded "Bulb replacement"). |
| 8 Bundle | "booking limit reached" | Use another member (a bundle counts as one booking toward the quota). |
| 9–10 Round | Round already committed / missing | Re-seed (`seed_demo.py --reset`) before the demo, or create a round live in the Allocation tab and submit two requests from members. |
| 9 Round | Optimal not proven | Say why: the exact solver stops at 2 s / 200 000 nodes and reports `optimal = false` honestly — allocation is NP-hard. |
| 11 Analytics | Looks empty | The range must cover the past 4 weeks (default). Re-seed if the database was reset. Fallback: `screenshots/board/analytics_fairness.png`. |
| 12 Tests | Still running | Show the last `pytest -q` line from the README, come back at the end. |
| Any | Anything else breaks live | Show `screenshots/smoke/` (27 step-by-step screenshots of the full flow, including the board and the Race Lab). |
