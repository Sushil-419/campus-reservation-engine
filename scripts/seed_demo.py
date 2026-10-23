"""Realistic demo data for the dev database (DATABASE_URL from .env).

    python scripts/seed_demo.py --reset

--reset is REQUIRED because this first deletes every waitlist entry,
reservation event, reservation, series, blackout and resource, plus the
demo users (email ending in "@demo.local") and their sessions/tokens. It
never deletes the admin or any other real user.

What it creates (deterministic for a given day: random.seed(42)):
  * 7 resources of mixed types/capacities/hours (one auto-approve, one
    weekdays-only, one capacity-20 hall). Halls and conference rooms are
    booking_mode "whole" (one booking takes the room; capacity = most
    people); the Projector Cart and the 30-seat Computer Lab are "units"
    pools. 12 approved demo members (password "demo1234").
  * The last 4 weeks of PAST bookings with a realistic status mix and
    matching reservation_events. These are inserted directly, because the
    API (correctly) refuses bookings that start in the past; they still
    respect each resource's hours and capacity (whole rooms never overlap,
    pools never exceed their units), so the EXCLUDE constraints are
    satisfied. Party sizes are realistic: rooms 2..capacity, units 1..3.
  * The next 2 weeks through the real service functions (create_reservation,
    create_series, create_blackout, join_waitlist), so every lock, policy and
    constraint applies: recurring series, a blackout, pending approvals and
    waitlist entries on full slots.
  * Data for every Analytics section (a second RNG, random.Random(7), so the
    data above stays the same): Focus Pod 1 requires check-in, so its past
    confirmed bookings are checked in or became no-shows; three past
    waitlist promotions and one expired
    waitlist entry (all direct inserts with matching events, like the past
    bookings); and one bundle (Seminar Hall + Projector Cart) booked through
    the real create_bundle at the best common free slot.

scripts/seed.py (the original minimal seed) is left untouched.
"""
import random
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    ApprovalStatus,
    BookingMode,
    Reservation,
    ReservationEvent,
    ReservationStatus,
    Resource,
    User,
    UserRole,
    encode_weekdays,
    is_exclusive,
)
from app.models import WaitlistEntry, WaitlistStatus  # noqa: E402
from app.services import bundles as bundle_service  # noqa: E402
from app.services import notifications  # noqa: E402
from app.services import reservations as reservation_service  # noqa: E402
from app.services import resources as resource_service  # noqa: E402
from app.services import series as series_service  # noqa: E402
from app.services import schedule_service  # noqa: E402
from app.services import waitlist as waitlist_service  # noqa: E402
from app.services.free_slots import peak_concurrency  # noqa: E402
from app.services.security import hash_password  # noqa: E402

DEMO_DOMAIN = "@demo.local"
S = ReservationStatus

WHOLE = {"booking_mode": BookingMode.whole}
RESOURCES = [
    # name, type, capacity, open, close, weekdays, location, extra
    ("Seminar Hall", "hall", 20, "08:00", "20:00", [1, 2, 3, 4, 5, 6, 7], "Main block, ground floor", WHOLE),
    ("Conference Room A", "room", 8, "09:00", "18:00", [1, 2, 3, 4, 5], "Block A, 1st floor", WHOLE),
    ("Conference Room B", "room", 6, "09:00", "18:00", [1, 2, 3, 4, 5, 6, 7], "Block A, 2nd floor", WHOLE),
    ("Focus Pod 1", "pod", 1, "08:00", "20:00", [1, 2, 3, 4, 5, 6, 7], "Library",
     {"auto_approve": True, "requires_checkin": True, "checkin_grace_minutes": 15}),
    ("3D Printer", "equipment", 1, "10:00", "17:00", [1, 2, 3, 4, 5, 6], "Maker lab",
     {"min_duration_minutes": 60, "max_duration_minutes": 240}),
    ("Projector Cart", "equipment", 2, "09:00", "18:00", [1, 2, 3, 4, 5, 6, 7], "AV store", {}),
    ("Computer Lab", "lab", 30, "09:00", "17:00", [1, 2, 3, 4, 5, 6], "Block C, ground floor", {}),
]
MEMBERS = ["Asha", "Ravi", "Meera", "Arjun", "Priya", "Kiran", "Neha", "Vikram", "Sana", "Rohan", "Divya", "Imran"]


def reset(db) -> None:
    demo_users = "SELECT id FROM users WHERE email LIKE '%" + DEMO_DOMAIN + "'"
    for stmt in (
        "DELETE FROM waitlist_entries",
        "DELETE FROM reservation_events",
        "DELETE FROM reservations",
        "DELETE FROM reservation_bundles",
        "DELETE FROM reservation_series",
        "DELETE FROM resource_blackouts",
        "DELETE FROM resources",
        f"DELETE FROM sessions WHERE user_id IN ({demo_users})",
        f"DELETE FROM email_tokens WHERE user_id IN ({demo_users})",
        f"DELETE FROM users WHERE email LIKE '%{DEMO_DOMAIN}'",
    ):
        db.execute(text(stmt))
    db.commit()


def make_resources(db) -> list[Resource]:
    out = []
    for name, rtype, cap, open_t, close_t, days, location, extra in RESOURCES:
        r = Resource(
            name=name, type=rtype, capacity=cap, location=location, timezone="Asia/Kolkata",
            description=f"Demo {rtype}", open_time=time.fromisoformat(open_t),
            close_time=time.fromisoformat(close_t), open_weekdays=encode_weekdays(days), **extra,
        )
        db.add(r)
        out.append(r)
    db.commit()
    return out


def make_members(db) -> list[User]:
    pw = hash_password("demo1234")
    users = [
        User(name=n, email=f"{n.lower()}{DEMO_DOMAIN}", role=UserRole.member,
             approval_status=ApprovalStatus.approved, email_verified=True, password_hash=pw)
        for n in MEMBERS
    ]
    db.add_all(users)
    db.commit()
    return users


def _durations(resource: Resource) -> list[int]:
    return [m for m in (30, 60, 90, 120, 180) if resource.min_duration_minutes <= m <= resource.max_duration_minutes]


def _party_size(rng, resource) -> int:
    """Realistic party: a whole room holds 2..capacity people, a pool booking
    takes 1..3 units (never more than the pool has)."""
    if resource.booking_mode == BookingMode.whole:
        return rng.randint(min(2, resource.capacity), resource.capacity)
    return rng.randint(1, min(3, resource.capacity))


def _random_slot(rng, resource, day):
    """A random half-hour-aligned slot inside the resource's local hours."""
    zone = ZoneInfo(resource.timezone)
    minutes = rng.choice(_durations(resource))
    open_m = resource.open_time.hour * 60 + resource.open_time.minute
    close_m = resource.close_time.hour * 60 + resource.close_time.minute
    latest = close_m - minutes
    if latest < open_m:
        return None
    start_m = open_m + 30 * rng.randint(0, (latest - open_m) // 30)
    start = datetime.combine(day, time(start_m // 60, start_m % 60), tzinfo=zone).astimezone(timezone.utc)
    return start, start + timedelta(minutes=minutes)


def seed_past(db, rng, resources, members, admin_id, today) -> int:
    """Past 4 weeks, inserted directly (see module docstring)."""
    count = 0
    open_days = {r.id: [d for d in range(1, 8) if r.open_weekdays & (1 << (d - 1))] for r in resources}
    for offset in range(28, 0, -1):
        day = today - timedelta(days=offset)
        for res in resources:
            if day.isoweekday() not in open_days[res.id]:
                continue
            placed: list[tuple[datetime, datetime, int, int]] = []  # active rows only
            exclusive = is_exclusive(res)
            for _ in range(rng.randint(1, min(2 + res.capacity // 3, 7))):
                slot = _random_slot(rng, res, day)
                if slot is None:
                    continue
                start, end = slot
                user = rng.choice(members)
                party = _party_size(rng, res)
                status = rng.choices(
                    [S.confirmed, S.cancelled, S.rejected, S.expired],
                    weights=[75, 12, 8, 5],
                )[0]
                if res.auto_approve and status in (S.rejected, S.expired):
                    status = S.confirmed  # auto-approved bookings are never pending
                active = status == S.confirmed
                if active:
                    overlapping = [p for p in placed if p[0] < end and p[1] > start]
                    if any(p[2] == user.id for p in overlapping):
                        continue  # no_user_duplicate_reservation
                    if exclusive and overlapping:
                        continue  # no_overlap: whole rooms / capacity 1 never overlap
                    if peak_concurrency(_as_rows(overlapping), start, end) + party > res.capacity:
                        continue  # not enough units left in the pool
                    placed.append((start, end, user.id, party))
                created = start - timedelta(days=rng.randint(1, 6), minutes=rng.randint(0, 600))
                r = Reservation(resource_id=res.id, user_id=user.id, start_time=start, end_time=end,
                                status=status, exclusive=exclusive, party_size=party,
                                created_at=created)
                db.add(r)
                db.flush()
                _past_events(db, rng, r, res, user, admin_id, created)
                count += 1
    db.commit()
    return count


class _Row:
    def __init__(self, s, e, party_size=1):
        self.start_time, self.end_time, self.party_size = s, e, party_size


def _as_rows(intervals):
    return [_Row(s, e, party) for s, e, _, party in intervals]


def _past_events(db, rng, r, res, user, admin_id, created):
    def ev(frm, to, at, actor, reason=None):
        db.add(ReservationEvent(reservation_id=r.id, actor_user_id=actor, from_status=frm,
                                to_status=to, reason=reason, created_at=at))

    if res.auto_approve:
        ev(None, S.confirmed, created, user.id, "auto-approved by resource policy")
        if r.status == S.cancelled:
            ev(S.confirmed, S.cancelled, created + timedelta(hours=rng.randint(1, 20)), user.id)
        return
    ev(None, S.pending, created, user.id)
    # approval latency: mostly minutes, sometimes hours
    decided = created + timedelta(minutes=int(rng.choice([rng.uniform(3, 45), rng.uniform(45, 600)])))
    decided = min(decided, r.start_time - timedelta(minutes=5))
    if r.status == S.confirmed:
        ev(S.pending, S.confirmed, decided, admin_id)
    elif r.status == S.rejected:
        ev(S.pending, S.rejected, decided, admin_id, rng.choice(["Room needed for an exam", "Maintenance planned", "Please book a smaller room"]))
    elif r.status == S.expired:
        ev(S.pending, S.expired, r.start_time, None, "approval window passed")
    elif r.status == S.cancelled:
        if rng.random() < 0.5:
            ev(S.pending, S.confirmed, decided, admin_id)
            ev(S.confirmed, S.cancelled, decided + timedelta(hours=rng.randint(1, 24)), user.id)
        else:
            ev(S.pending, S.cancelled, decided, user.id)


def seed_future(db, rng, resources, members, admin, today) -> dict:
    """Next 2 weeks through the real services (locks, policies, constraints)."""
    by_name = {r.name: r for r in resources}
    stats = {"singles": 0, "approved": 0, "series": 0, "blackouts": 0, "waitlist": 0}
    created_ids = []

    # Recurring series first (they count as one toward quota).
    for member, resource, rule in (
        (members[0], by_name["Conference Room B"],
         dict(frequency="weekly", interval=1, weekdays=[1, 3], local_start_time=time(10, 0),
              duration_minutes=60, occurrence_count=4, party_size=5)),
        (members[1], by_name["Seminar Hall"],
         dict(frequency="daily", interval=2, weekdays=None, local_start_time=time(16, 0),
              duration_minutes=90, occurrence_count=5, party_size=14)),
        (members[5], by_name["Computer Lab"],
         dict(frequency="weekly", interval=1, weekdays=[2, 4], local_start_time=time(14, 0),
              duration_minutes=120, occurrence_count=4, party_size=3)),
    ):
        rule.update(resource_id=resource.id, start_date=today + timedelta(days=1), until_date=None)
        try:
            series_service.create_series(db, member, rule, "skip_conflicts")
            stats["series"] += 1
        except Exception as e:
            print(f"  series skipped: {e}")

    # Single bookings at random valid times.
    for member in members:
        for _ in range(rng.randint(1, 3)):
            res = rng.choice([r for r in resources if r.name != "Focus Pod 1"])
            day = today + timedelta(days=rng.randint(1, 14))
            slot = _random_slot(rng, res, day)
            if slot is None:
                continue
            try:
                r = reservation_service.create_reservation(
                    db, res.id, member.id, *slot, party_size=_party_size(rng, res)
                )
                created_ids.append(r.id)
                stats["singles"] += 1
            except Exception:
                pass  # closed day, full, quota... the real rules said no

    # Approve most, leave a few pending for the approvals demo.
    for rid in created_ids:
        if rng.random() < 0.7:
            try:
                reservation_service.approve_reservation(db, rid, acting_user=admin)
                stats["approved"] += 1
            except Exception:
                pass

    # A maintenance blackout next week (forcing out anything in the way).
    cart = by_name["Projector Cart"]
    zone = ZoneInfo(cart.timezone)
    bday = today + timedelta(days=7)
    if admin is not None:
        resource_service.create_blackout(
            db, cart.id,
            datetime.combine(bday, time(9, 0), tzinfo=zone), datetime.combine(bday, time(13, 0), tzinfo=zone),
            "Bulb replacement", admin, force=True,
        )
        stats["blackouts"] += 1

    # A full slot on the auto-approve pod, with two people waiting for it.
    pod = by_name["Focus Pod 1"]
    zone = ZoneInfo(pod.timezone)
    wday = today + timedelta(days=3)
    start = datetime.combine(wday, time(11, 0), tzinfo=zone)
    end = start + timedelta(hours=1)
    try:
        reservation_service.create_reservation(db, pod.id, members[2].id, start, end)
    except Exception as e:
        print(f"  pod booking skipped: {e}")
    for member in members[3:5]:
        try:
            waitlist_service.join_waitlist(db, member, pod.id, start, end)
            stats["waitlist"] += 1
        except Exception as e:
            print(f"  waitlist join skipped: {e}")
    return stats


def _free_block(db, resource, days, hours=3):
    """First local (day, start hour) with `hours` consecutive free hours on
    the resource (no active booking, inside opening hours), or None."""
    zone = ZoneInfo(resource.timezone)
    for day in days:
        if day.isoweekday() not in [d for d in range(1, 8) if resource.open_weekdays & (1 << (d - 1))]:
            continue
        for hour in range(resource.open_time.hour, resource.close_time.hour - hours + 1):
            start = datetime.combine(day, time(hour), tzinfo=zone)
            end = start + timedelta(hours=hours)
            busy = db.execute(text(
                "SELECT 1 FROM reservations WHERE resource_id = :r AND status IN ('pending','confirmed') "
                "AND start_time < :e AND end_time > :s LIMIT 1"), {"r": resource.id, "s": start, "e": end}).first()
            if busy is None:
                return day, hour
    return None


def _event(db, reservation_id, frm, to, at, actor, reason=None):
    db.add(ReservationEvent(reservation_id=reservation_id, actor_user_id=actor, from_status=frm,
                            to_status=to, reason=reason, created_at=at))


def _insert(db, resource, user, start, end, status, created, party=None):
    r = Reservation(resource_id=resource.id, user_id=user.id, start_time=start, end_time=end, status=status,
                    exclusive=is_exclusive(resource), party_size=party or min(2, resource.capacity),
                    created_at=created)
    db.add(r)
    db.flush()
    return r


def _past_slot(db, resource, today, first_offset, hours=1):
    """A free past (start, end) on the resource, searching from
    `first_offset` days ago towards today."""
    days = [today - timedelta(days=o) for o in range(first_offset, 1, -1)]
    found = _free_block(db, resource, days, hours)
    if found is None:
        return None
    day, hour = found
    start = datetime.combine(day, time(hour), tzinfo=ZoneInfo(resource.timezone))
    return start, start + timedelta(hours=hours)


def seed_checkins(db, rng, resources, today) -> dict:
    """Past confirmed bookings on check-in resources: every 6th was a
    no-show (released by the job at start + grace), the rest checked in
    between 10 minutes before the start and the end of the grace period."""
    stats = {"checked_in": 0, "no_shows": 0}
    for res in (r for r in resources if r.requires_checkin):
        rows = db.query(Reservation).filter(
            Reservation.resource_id == res.id, Reservation.status == S.confirmed,
            Reservation.start_time < datetime.combine(today, time(0), tzinfo=ZoneInfo(res.timezone)),
        ).order_by(Reservation.start_time).all()
        no_show_ids = {r.id for r in rows[3::6]}
        for r in rows:
            if r.id in no_show_ids:
                r.status = S.no_show
                _event(db, r.id, S.confirmed, S.no_show, r.start_time + timedelta(minutes=res.checkin_grace_minutes),
                       None, f"no check-in within {res.checkin_grace_minutes} minutes")
                stats["no_shows"] += 1
            else:
                r.checked_in_at = r.start_time + timedelta(minutes=rng.randint(-10, res.checkin_grace_minutes - 1))
                stats["checked_in"] += 1
    db.commit()
    return stats


def seed_waitlist_history(db, rng, resources, members, admin_id, today) -> dict:
    """Past waitlist activity: three entries promoted when the holder
    cancelled (wait = promotion time - join time) and one that expired."""
    by_name = {r.name: r for r in resources}
    who = {m.name: m for m in members}
    stats = {"promoted": 0, "expired": 0}
    for room_name, holder_name, waiter_name, offset in (("Conference Room A", "Arjun", "Priya", 24),
                                                        ("Seminar Hall", "Meera", "Sana", 16),
                                                        ("Conference Room B", "Imran", "Divya", 10)):
        room, holder, waiter = by_name[room_name], who[holder_name], who[waiter_name]
        slot = _past_slot(db, room, today, offset)
        if slot is None:
            print(f"  waitlist promotion on {room_name} skipped: no free past hour")
            continue
        start, end = slot
        booked = start - timedelta(days=5)
        joined = start - timedelta(days=3, hours=rng.randint(0, 6))
        cancelled_at = joined + timedelta(hours=rng.randint(2, 30), minutes=rng.randint(0, 59))
        held = _insert(db, room, holder, start, end, S.cancelled, booked)
        _event(db, held.id, None, S.pending, booked, holder.id)
        _event(db, held.id, S.pending, S.confirmed, booked + timedelta(minutes=30), admin_id)
        _event(db, held.id, S.confirmed, S.cancelled, cancelled_at, holder.id)
        promoted = _insert(db, room, waiter, start, end, S.confirmed, cancelled_at + timedelta(seconds=1))
        _event(db, promoted.id, None, S.pending, promoted.created_at, None, "promoted from waitlist")
        _event(db, promoted.id, S.pending, S.confirmed, promoted.created_at + timedelta(minutes=20), admin_id)
        db.add(WaitlistEntry(user_id=waiter.id, resource_id=room.id, start_time=start, end_time=end,
                             status=WaitlistStatus.promoted, party_size=promoted.party_size,
                             promoted_reservation_id=promoted.id, created_at=joined))
        stats["promoted"] += 1
    # One wait that never came true: the slot stayed taken until it started.
    taken = db.query(Reservation).filter(
        Reservation.resource_id == by_name["Focus Pod 1"].id, Reservation.status == S.confirmed,
        Reservation.start_time < datetime.combine(today, time(0), tzinfo=timezone.utc),
    ).order_by(Reservation.start_time.desc()).first()
    if taken is not None:
        waiter = next(m for m in members if m.id != taken.user_id)
        db.add(WaitlistEntry(user_id=waiter.id, resource_id=taken.resource_id, start_time=taken.start_time,
                             end_time=taken.end_time, status=WaitlistStatus.expired, party_size=1,
                             created_at=taken.start_time - timedelta(days=1)))
        stats["expired"] += 1
    db.commit()
    return stats


def seed_bundle(db, resources, members, today) -> dict:
    """One bundle through the real services: the best common free slot for
    Seminar Hall (15 people) + Projector Cart (1 unit) in the next week,
    booked all-or-nothing with create_bundle."""
    by_name = {r.name: r for r in resources}
    hall, cart = by_name["Seminar Hall"], by_name["Projector Cart"]
    for member in (m for m in members if m.name in ("Meera", "Arjun", "Ravi")):
        found = schedule_service.common_slots(
            db, member, resource_ids=[hall.id, cart.id], duration_minutes=120,
            date_from=today + timedelta(days=2), date_to=today + timedelta(days=8),
            party_sizes={hall.id: 15, cart.id: 1}, limit=1,
        )
        db.rollback()  # end the read transaction before booking
        if not found["slots"]:
            continue
        slot = found["slots"][0]
        try:
            bundle, items = bundle_service.create_bundle(
                db, member.id, [(hall.id, 15), (cart.id, 1)], slot["start"], slot["end"])
        except Exception as e:  # quota... the real rules said no
            print(f"  bundle for {member.name} skipped: {e}")
            continue
        return {"bundles": 1, "owner": member.name, "items": len(items),
                "start": slot["start"].astimezone(ZoneInfo(hall.timezone)).strftime("%a %d %b %H:%M")}
    return {"bundles": 0}


def main() -> int:
    if "--reset" not in sys.argv:
        print(__doc__)
        print("Refusing to run without --reset (it deletes existing reservations and resources).")
        return 2
    rng = random.Random(42)
    # Demo users have fake addresses; don't "send" them approval emails.
    notifications.deliver = lambda emails: None

    db = SessionLocal()
    try:
        reset(db)
        admin = db.query(User).filter(User.email == settings.admin_email).one_or_none()
        resources = make_resources(db)
        members = make_members(db)
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        past = seed_past(db, rng, resources, members, admin.id if admin else None, today)
        future = seed_future(db, rng, resources, members, admin, today)
        # A second RNG, so everything above stays exactly as it was.
        extra = random.Random(7)
        admin_id = admin.id if admin else None
        checkins = seed_checkins(db, extra, resources, today)
        waitlist_history = seed_waitlist_history(db, extra, resources, members, admin_id, today)
        bundle = seed_bundle(db, resources, members, today)

        print("Demo data created.")
        print(f"  resources: {len(resources)}, demo members: {len(members)} (password demo1234)")
        print(f"  past bookings (direct insert): {past}")
        print(f"  future via services: {future}")
        print(f"  check-in history: {checkins}")
        print(f"  past waitlist: {waitlist_history}")
        print(f"  bundle: {bundle}")
        for table in ("users", "resources", "reservations", "reservation_events", "reservation_series",
                      "resource_blackouts", "waitlist_entries", "reservation_bundles"):
            print(f"  {table:20s} {db.execute(text(f'SELECT count(*) FROM {table}')).scalar()}")
        for status, n in db.execute(text("SELECT status, count(*) FROM reservations GROUP BY 1 ORDER BY 1")):
            print(f"    reservations[{status}] = {n}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
