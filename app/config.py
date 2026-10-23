import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:pass@localhost:5432/booking")
TEST_DATABASE_URL: str = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://postgres:pass@localhost:5432/booking_test")
NAIVE_DELAY_MS: int = int(os.getenv("NAIVE_DELAY_MS", "0"))

# Operating hours by resource type: (start_hour, end_hour)
OPERATING_HOURS: dict[str, tuple[int, int]] = {
    "classroom": (8, 18),
    "lab": (8, 18),
    "project_space": (8, 18),
    "research_center": (8, 18),
    "seminar_hall": (8, 20),
    "auditorium": (8, 20),
    "sports": (6, 20),
}
DEFAULT_OPERATING_HOURS: tuple[int, int] = (8, 18)

# Pool settings (per worker)
POOL_SIZE: int = 25
MAX_OVERFLOW: int = 25
