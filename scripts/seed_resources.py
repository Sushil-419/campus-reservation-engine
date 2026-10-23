"""Seed the resources table with campus rooms/labs/halls.

Run: python -m scripts.seed_resources
"""
from app.db import SessionLocal
from app.models import Resource


def _numbered(building: str, floor: int, start: int, end: int,
              rtype: str = "classroom", dept: str | None = None) -> list[dict]:
    """Generate numbered rooms like 'Building 101', 'Building 102', ..."""
    return [
        {"name": f"{building} {n}", "building": building, "floor": floor,
         "type": rtype, "department": dept, "capacity": None, "is_active": True}
        for n in range(start, end + 1)
    ]


def _named(name: str, building: str, floor: int,
           rtype: str, dept: str | None = None) -> dict:
    """Single named resource."""
    return {
        "name": name, "building": building, "floor": floor,
        "type": rtype, "department": dept, "capacity": None, "is_active": True,
    }


def _build_resources() -> list[dict]:
    resources = []

    # --- R H Kulkarni ---
    bldg = "R H Kulkarni"
    resources += _numbered(bldg, 1, 101, 108)
    resources.append(_named(f"{bldg} Tinkering Lab", bldg, 1, "project_space"))
    resources.append(_named(f"{bldg} DTSI 1", bldg, 1, "project_space"))
    resources.append(_named(f"{bldg} DTSI 2", bldg, 1, "project_space"))

    resources += _numbered(bldg, 2, 201, 208)
    resources.append(_named(f"{bldg} DTSI 3", bldg, 2, "project_space"))
    resources.append(_named(f"{bldg} DTSI 4", bldg, 2, "project_space"))

    resources += _numbered(bldg, 3, 301, 312)  # 301-310 + 311,312 extra
    resources.append(_named(f"{bldg} DTSI 5", bldg, 3, "project_space"))
    resources.append(_named(f"{bldg} DTSI 6", bldg, 3, "project_space"))
    resources.append(_named(f"{bldg} Lab 301", bldg, 3, "lab"))

    # --- CLITE ---
    bldg = "CLITE"
    resources += _numbered(bldg, 1, 101, 108, "lab")
    resources += _numbered(bldg, 2, 201, 205, "lab")
    resources.append(_named("CLITE CEVI", bldg, 2, "lab"))
    resources.append(_named("CLITE AI Research Center", bldg, 2, "research_center"))
    resources.append(_named("CLITE Cloud Computing Center", bldg, 2, "research_center"))

    # --- Main ---
    bldg = "Main"
    resources += _numbered(bldg, 0, 101, 120)
    resources += _numbered(bldg, 1, 201, 220)

    # --- EEE ---
    bldg = "EEE"
    dept = "EEE"
    resources += _numbered(bldg, 0, 101, 120, "classroom", dept)
    resources += _numbered(bldg, 1, 201, 220, "classroom", dept)

    # --- CLH ---
    bldg = "CLH"
    resources += _numbered(bldg, 0, 101, 110, "lab")
    resources += _numbered(bldg, 1, 201, 215, "lab")
    resources += _numbered(bldg, 2, 301, 315)

    # --- School of Mechanical Engineering ---
    bldg = "School of Mechanical Engineering"
    dept = "Mechanical"
    resources += _numbered(bldg, 0, 101, 110, "lab", dept)
    resources += _numbered(bldg, 1, 201, 215, "lab", dept)
    resources += _numbered(bldg, 2, 301, 315, "classroom", dept)

    # --- Architecture ---
    bldg = "Architecture"
    dept = "Architecture"
    resources.append(_named("Architecture Seminar Hall 1", bldg, 0, "seminar_hall", dept))
    resources.append(_named("Architecture Seminar Hall 2", bldg, 0, "seminar_hall", dept))
    resources += _numbered(bldg, 0, 101, 110, "classroom", dept)
    resources += _numbered(bldg, 1, 201, 220, "classroom", dept)

    # --- Civil ---
    bldg = "Civil"
    dept = "Civil"
    resources += _numbered(bldg, 0, 101, 115, "classroom", dept)
    resources += _numbered(bldg, 1, 201, 220, "classroom", dept)

    # --- ENC ---
    bldg = "ENC"
    resources += _numbered(bldg, 0, 101, 110)
    resources += _numbered(bldg, 1, 201, 220)
    resources.append(_named("ENC Seminar Hall 1", bldg, 1, "seminar_hall"))
    resources += _numbered(bldg, 2, 301, 320)
    resources.append(_named("ENC Seminar Hall 2", bldg, 2, "seminar_hall"))
    resources += _numbered(bldg, 3, 401, 420)
    resources.append(_named("ENC Seminar Hall 3", bldg, 3, "seminar_hall"))
    resources.append(_named("ENC Seminar Hall 4", bldg, 3, "seminar_hall"))

    # --- Biotech ---
    bldg = "Biotech"
    dept = "Biotechnology"
    resources.append(_named("Biotech Seminar Hall", bldg, 0, "seminar_hall", dept))
    for i in range(1, 6):
        resources.append(_named(f"Biotech Lab {i}", bldg, 1, "lab", dept))
    for i in range(1, 6):
        resources.append(_named(f"Biotech {100 + i}", bldg, 1, "classroom", dept))

    # --- Deshpande Foundation Auditorium ---
    resources.append(_named(
        "Deshpande Foundation Auditorium", "Deshpande Foundation", 0, "auditorium"
    ))

    # --- Sports ---
    bldg = "Sports"
    resources.append(_named("Basketball Court", bldg, 0, "sports"))
    resources.append(_named("Tennis Court", bldg, 0, "sports"))
    resources.append(_named("Indoor Sports Area", bldg, 0, "sports"))

    return resources


def seed_resources():
    db = SessionLocal()
    try:
        existing = db.query(Resource).count()
        if existing > 0:
            print(f"Resources table already has {existing} rows — skipping.")
            return

        all_resources = _build_resources()
        objs = [Resource(**r) for r in all_resources]
        db.add_all(objs)
        db.commit()
        print(f"Seeded {len(objs)} resources.")

        # Summary by building
        from collections import Counter
        by_building = Counter(r["building"] for r in all_resources)
        for bldg, count in sorted(by_building.items()):
            print(f"  {bldg}: {count} resources")
    finally:
        db.close()


if __name__ == "__main__":
    seed_resources()
