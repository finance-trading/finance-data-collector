"""One-off sync of research_annotation from local Postgres to Supabase.

Reads the full local ``research_annotation`` table (SQLAlchemy) and bulk-upserts
it into the Supabase-hosted table via psycopg ``executemany`` in one round trip.
Idempotent: re-running only updates existing tickers.

Usage:
    FDC_DATABASE_URL=postgresql+psycopg://fdc:fdc@localhost:5432/fdc \
    FDC_TARGET_DATABASE_URL=postgresql+psycopg://postgres.<REF>:pw@<POOLER>:6543/postgres?sslmode=require \
    uv run python -m scripts.sync_research_to_supabase
"""

from __future__ import annotations

import os

import psycopg
from psycopg.types.json import Jsonb
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from fdc.models import ResearchAnnotation

_LOCAL_DEFAULT = "postgresql+psycopg://fdc:fdc@localhost:5432/fdc"

# Scalar + timestamp columns, in stable order. watch_items is appended last in
# the SQL column list (it is the only JSONB column).
_COLS = [
    "observe_low", "observe_high", "entry_low", "entry_high",
    "add_low", "add_high", "reduce_low", "reduce_high",
    "intrinsic_value", "scen_bear", "scen_base", "scen_bull",
    "created_at", "updated_at",
]


def _row_params(r: ResearchAnnotation) -> tuple:
    return (r.ticker, *(getattr(r, c) for c in _COLS), Jsonb(r.watch_items))


def _psycopg_conn(url: str) -> psycopg.Connection:
    conn = psycopg.connect(url)
    conn.autocommit = False
    return conn


def sync() -> int:
    local_url = os.getenv("FDC_DATABASE_URL", _LOCAL_DEFAULT)
    target_url = os.environ.get("FDC_TARGET_DATABASE_URL")
    if not target_url:
        raise SystemExit("set FDC_TARGET_DATABASE_URL (Supabase pooler connection string)")

    local = sessionmaker(bind=create_engine(local_url))()
    rows = local.query(ResearchAnnotation).all()
    print(f"local research_annotation: {len(rows)} rows")

    # ticker + scalars + watch_items (last) must line up with _row_params.
    all_cols = ["ticker", *_COLS, "watch_items"]
    placeholders = ", ".join("%s" for _ in all_cols)
    col_list = ", ".join(all_cols)
    sets = ", ".join(f"{c}=EXCLUDED.{c}" for c in _COLS) + ", watch_items=EXCLUDED.watch_items"
    sql = (
        f"INSERT INTO research_annotation ({col_list}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT (ticker) DO UPDATE SET {sets}"
    )

    params = [_row_params(r) for r in rows]
    with _psycopg_conn(target_url) as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, params)
        conn.commit()
    print(f"synced {len(params)} rows to target")
    return len(params)


if __name__ == "__main__":
    sync()
