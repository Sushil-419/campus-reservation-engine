import os
from dotenv import load_dotenv

load_dotenv()

def _normalize_db_url(url: str) -> str:
    """Normalize cloud database URLs (postgres://, postgresql://) to psycopg 3 driver."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://") and not url.startswith("postgresql+"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url

_raw_db_url = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:pass@localhost:5432/booking")
DATABASE_URL: str = _normalize_db_url(_raw_db_url)

_raw_test_db_url = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://postgres:pass@localhost:5432/booking_test")
TEST_DATABASE_URL: str = _normalize_db_url(_raw_test_db_url)

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
POOL_SIZE: int = int(os.getenv("POOL_SIZE", "10"))
MAX_OVERFLOW: int = int(os.getenv("MAX_OVERFLOW", "10"))
