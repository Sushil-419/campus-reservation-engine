import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root reliably regardless of current working directory
_base_dir = Path(__file__).resolve().parent.parent
_env_file = _base_dir / ".env"
if _env_file.exists():
    load_dotenv(dotenv_path=_env_file, override=True)
else:
    load_dotenv(override=True)

def _normalize_db_url(url: str) -> str:
    """Normalize cloud database URLs (postgres://, postgresql://) to psycopg 3 driver."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://") and not url.startswith("postgresql+"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url

is_render = os.getenv("RENDER") == "true" or "onrender.com" in os.getenv("RENDER_EXTERNAL_HOSTNAME", "")
_raw_db_url = os.getenv("DATABASE_URL")
if not _raw_db_url:
    if is_render:
        raise RuntimeError(
            "\n====================================================================================\n"
            "CRITICAL CONFIGURATION ERROR ON RENDER:\n"
            "The 'DATABASE_URL' environment variable is NOT set in your Web Service!\n"
            "To fix this:\n"
            "1. Open Render Dashboard -> 'campus-db' -> Info -> Copy 'Internal Database URL'\n"
            "2. Open Render Dashboard -> 'campus-reservation-engine' -> Environment -> Add 'DATABASE_URL'\n"
            "====================================================================================\n"
        )
    _raw_db_url = "postgresql+psycopg://postgres:pass@localhost:5433/booking"
DATABASE_URL: str = _normalize_db_url(_raw_db_url)

_raw_test_db_url = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://postgres:pass@localhost:5433/booking_test")
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
