"""Filesystem locations for the centralized SEC filing store."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEC_ROOT = PROJECT_ROOT / "sec"
CACHE_DIR = SEC_ROOT / ".cache"


def default_output_dir(ticker: str) -> Path:
    """Return the canonical filing directory for a ticker."""
    return SEC_ROOT / ticker.upper()
