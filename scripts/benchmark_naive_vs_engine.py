"""Benchmark: a naive check-then-insert booking vs. this project's engine.

    python scripts/benchmark_naive_vs_engine.py [--threads 50] [--rounds 5] [--think-ms 20] [--quick]

Creates its OWN throwaway database (resvdb_bench), migrates it, and drops it
at the end, also on failure. It never touches the dev or test databases.

Scenarios (each round = N threads released at the same instant):
  A  naive    SELECT overlap-check -> sleep(think) -> INSERT into a table with
              no exclusion constraint and no locks. Rows > 1 = double bookings.
  B  engine   the real create_reservation() on one capacity-1 resource:
              exactly 1 success per round.
  C  engine   capacity-5 resource: exactly 5 successes per round.
  D  engine   N requests on N DIFFERENT resources: all succeed, and they don't
              serialize behind each other (compare wall time with B).
"""
import argparse
import json
import statistics
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

ADMIN_URL = "postgresql+psycopg://postgres:resvdb_dev_pw@127.0.0.1:5432/postgres"
BENCH_DB = "resvdb_bench"
BENCH_URL = f"postgresql+psycopg://postgres:resvdb_dev_pw@127.0.0.1:5432/{BENCH_DB}"
RESULTS_DIR = PROJECT_ROOT / "scripts" / "benchmark_results"


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--threads", type=int, default=50, help="concurrent requests per round (default 50)")
    p.add_argument("--rounds", type=int, default=5, help="rounds per scenario (default 5)")
    p.add_argument(
        "--think-ms", type=int, default=20,
        help="sleep between the naive overlap check and its INSERT (default 20). It only WIDENS the race "
             "window so the naive bug reproduces reliably on a fast laptop; the bug exists without it, "
             "it just shows up less often. The engine scenarios have no sleep.",
    )
    p.add_argument("--quick", action="store_true", help="shortcut for --threads 20 --rounds 2")
    args = p.parse_args()
    if args.quick:
        args.threads, args.rounds = 20, 2
    return args


def create_db():
    from sqlalchemy import create_engine, text
    e = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with e.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {BENCH_DB} WITH (FORCE)"))
        c.execute(text(f"CREATE DATABASE {BENCH_DB}"))
    e.dispose()


def drop_db():
    from sqlalchemy import create_engine, text
    e = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with e.connect() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {BENCH_DB} WITH (FORCE)"))
    e.dispose()


def run_round(n, fn):
    """Release n threads at once; return (results, latencies_ms, wall_ms)."""
    barrier = threading.Barrier(n + 1)
    results = [None] * n
    lat = [0.0] * n

    def worker(i):
        barrier.wait()
        t0 = time.perf_counter()
        try:
            results[i] = fn(i)
        except Exception as e:  # recorded, not raised
            results[i] = f"error: {type(e).__name__}"
        lat[i] = (time.perf_counter() - t0) * 1000

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    barrier.wait()
    t0 = time.perf_counter()
    for t in threads:
        t.join()
    return results, lat, (time.perf_counter() - t0) * 1000


def summarize(name, rounds_successes, expected, latencies, wall_ms_total, n_requests, double_bookings=None):
    lat = sorted(latencies)
    return {
        "scenario": name,
        "successes_per_round": rounds_successes,
        "expected_per_round": expected,
        "correct": all(s == expected for s in rounds_successes),
        "double_bookings": double_bookings if double_bookings is not None else 0,
        "p50_ms": round(statistics.median(lat), 1),
        "p95_ms": round(lat[max(0, int(len(lat) * 0.95) - 1)], 1),
        "throughput_rps": round(n_requests / (wall_ms_total / 1000), 1),
        "wall_ms_per_round": round(wall_ms_total / len(rounds_successes), 1),
    }


def main() -> int:
    args = parse_args()
    import os
    os.environ["DATABASE_URL"] = BENCH_URL  # before any app import
    os.environ["JOBS_ENABLED"] = "false"
    os.environ["REALTIME_ENABLED"] = "false"

    create_db()
    try:
        from alembic import command
        from alembic.config import Config
        cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
        command.upgrade(cfg, "head")
        return run(args)
    finally:
        from app.database import engine as app_engine
        app_engine.dispose()
        drop_db()
        print(f"\n(dropped throwaway database {BENCH_DB})")


def run(args) -> int:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from app.models import ApprovalStatus, Resource, User, UserRole, encode_weekdays
    from app.services import notifications
    from app.services import reservations as reservation_service

    notifications.deliver = lambda emails: None
    n, rounds = args.threads, args.rounds
    # A pool big enough that every thread gets its own connection at once.
    engine = create_engine(BENCH_URL, pool_size=n + 5, max_overflow=5,
                           connect_args={"options": "-c timezone=utc"})
    Session = sessionmaker(bind=engine, autoflush=False)

    always_open = dict(timezone="UTC", open_time=datetime.strptime("00:00", "%H:%M").time(),
                       close_time=datetime.strptime("23:59", "%H:%M").time(),
                       open_weekdays=encode_weekdays([1, 2, 3, 4, 5, 6, 7]))
    db = Session()
    single = Resource(name="Bench single", type="room", capacity=1, **always_open)
    five = Resource(name="Bench five", type="room", capacity=5, **always_open)
    many = [Resource(name=f"Bench D{i}", type="room", capacity=1, **always_open) for i in range(n)]
    db.add_all([single, five, *many])
    # fresh users per (scenario, round, thread) so the per-user quota never interferes
    users = {
        key: [User(name=f"{key}-{i}", email=f"{key}-{i}@bench.local", role=UserRole.member,
                   approval_status=ApprovalStatus.approved, email_verified=True) for i in range(n)]
        for key in [f"{s}{r}" for s in "BCD" for r in range(rounds)]
    }
    for group in users.values():
        db.add_all(group)
    db.commit()
    ids = {
        "single": single.id, "five": five.id, "many": [r.id for r in many],
        "users": {k: [u.id for u in v] for k, v in users.items()},
    }
    db.close()

    def slot(round_no):
        start = datetime(2030, 1, 1, 10, tzinfo=timezone.utc) + timedelta(days=round_no)
        return start, start + timedelta(hours=1)

    results = []

    # ── A: naive ──
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE naive_reservations (
                id serial PRIMARY KEY, resource_id int, user_id int,
                start_time timestamptz, end_time timestamptz, status text
            )"""))
    succ, lats, wall = [], [], 0.0
    doubles = 0
    for r in range(rounds):
        start, end = slot(r)

        def naive_book(i):
            with engine.connect() as conn:
                with conn.begin():
                    taken = conn.execute(text(
                        "SELECT count(*) FROM naive_reservations WHERE resource_id = 1 "
                        "AND status IN ('pending','confirmed') AND start_time < :e AND end_time > :s"
                    ), {"s": start, "e": end}).scalar()
                    if taken:
                        return False
                    time.sleep(args.think_ms / 1000)  # widen the race window
                    conn.execute(text(
                        "INSERT INTO naive_reservations (resource_id, user_id, start_time, end_time, status) "
                        "VALUES (1, :u, :s, :e, 'pending')"
                    ), {"u": i, "s": start, "e": end})
                    return True

        res, lat, w = run_round(n, naive_book)
        ok = sum(1 for x in res if x is True)
        succ.append(ok)
        doubles += max(0, ok - 1)
        lats += lat
        wall += w
    results.append(summarize("A naive (no constraint, no locks)", succ, 1, lats, wall, n * rounds, doubles))

    # ── B/C/D: the real engine ──
    def engine_scenario(label, key, resource_for, expected):
        succ, lats, wall = [], [], 0.0
        for r in range(rounds):
            start, end = slot(r)
            user_ids = ids["users"][f"{key}{r}"]

            def book(i):
                s = Session()
                try:
                    reservation_service.create_reservation(s, resource_for(i), user_ids[i], start, end)
                    return True
                except reservation_service.ReservationConflictError:
                    return False
                finally:
                    s.close()

            res, lat, w = run_round(n, book)
            errors = [x for x in res if isinstance(x, str)]
            if errors:
                print(f"  {label}: unexpected errors {errors[:3]}")
            succ.append(sum(1 for x in res if x is True))
            lats += lat
            wall += w
        return summarize(label, succ, expected, lats, wall, n * rounds)

    results.append(engine_scenario("B engine, capacity 1", "B", lambda i: ids["single"], 1))
    results.append(engine_scenario("C engine, capacity 5", "C", lambda i: ids["five"], 5))
    results.append(engine_scenario("D engine, N different resources", "D", lambda i: ids["many"][i], n))

    # Count double bookings from the database itself: active rows above
    # capacity, summed over every round's slot.
    with engine.connect() as conn:
        for res_id, cap, label in ((ids["single"], 1, "B"), (ids["five"], 5, "C")):
            over = conn.execute(text(
                "SELECT COALESCE(SUM(GREATEST(c - :cap, 0)), 0) FROM (SELECT count(*) c FROM reservations "
                "WHERE resource_id = :r AND status IN ('pending','confirmed') GROUP BY start_time) x"
            ), {"r": res_id, "cap": cap}).scalar()
            for row in results:
                if row["scenario"].startswith(label):
                    row["double_bookings"] = int(over)
    engine.dispose()

    print_and_save(args, results)
    return 0 if all(r["correct"] for r in results[1:]) else 1


def print_and_save(args, results):
    cols = ["scenario", "successes_per_round", "double_bookings", "p50_ms", "p95_ms", "throughput_rps", "wall_ms_per_round"]
    header = f"\nthreads={args.threads} rounds={args.rounds} think_ms={args.think_ms}"
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in results:
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    print(header)
    print("\n".join(lines))
    b = next(r for r in results if r["scenario"].startswith("B"))
    d = next(r for r in results if r["scenario"].startswith("D"))
    print(f"\nD vs B wall time per round: {d['wall_ms_per_round']} ms vs {b['wall_ms_per_round']} ms "
          f"({d['successes_per_round'][0]} successful bookings vs {b['successes_per_round'][0]}).")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    tag = "quick" if args.quick else f"t{args.threads}-r{args.rounds}"
    meta = {"threads": args.threads, "rounds": args.rounds, "think_ms": args.think_ms, "results": results}
    (RESULTS_DIR / f"benchmark_{stamp}_{tag}.json").write_text(json.dumps(meta, indent=2))
    (RESULTS_DIR / f"benchmark_{stamp}_{tag}.md").write_text(header.strip() + "\n\n" + "\n".join(lines) + "\n")
    print(f"saved to {RESULTS_DIR}/benchmark_{stamp}_{tag}.(json|md)")


if __name__ == "__main__":
    sys.exit(main())
