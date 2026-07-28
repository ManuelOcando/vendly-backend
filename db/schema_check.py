"""
Check at startup that the database looks the way the code expects.

Why this exists: on 2026-07-27 an audit found 41 queries naming columns or
tables that do not exist. Every one was wrapped in a try/except, so nothing
crashed - features just quietly did not happen. Carts had been broken for days,
no seller had ever received an alert, and the dashboard permanently reported
WhatsApp as disconnected. Nothing in any log said so.

The check runs each table's expected column list through the same client the
application uses, because that is what actually matters: PostgREST rejects a
select naming an unknown column, which is exactly the failure the audit found.
Querying information_schema would test a path the backend never takes - and the
backend cannot reach it anyway, since it talks to Postgres through PostgREST.

It never raises and never blocks. A drifted schema should be loud in the boot
log, not a reason the service refuses to start - the rest of the application may
be perfectly usable.
"""
import asyncio
import logging
from typing import Dict, List, Optional, Tuple

from db.expected_schema import EXPECTED_SCHEMA
from db.supabase import get_supabase_client

logger = logging.getLogger(__name__)

# PostgREST names the offending column in its error, so one request per table is
# enough to learn which table is wrong. Individual columns are then narrowed down
# only for the tables that failed, which keeps the happy path at one request per
# table.
# Verified against this project's PostgREST rather than guessed:
#   unknown column -> 42703  "column orders.total_amount does not exist"
#   unknown table  -> PGRST205  "Could not find the table 'public.x' in the
#                               schema cache"
# 42P01 is what raw Postgres answers; PostgREST resolves tables against its own
# schema cache and never surfaces it, but it is matched too in case the error
# arrives from a direct connection.
_UNDEFINED_COLUMN = "42703"
_MISSING_TABLE_CODES = ("pgrst205", "42p01")


def _looks_like_missing_table(error: str) -> bool:
    lowered = error.lower()
    return (
        any(code in lowered for code in _MISSING_TABLE_CODES)
        or "could not find the table" in lowered
        or ("relation" in lowered and "does not exist" in lowered)
    )


def _looks_like_missing_column(error: str) -> bool:
    lowered = error.lower()
    return _UNDEFINED_COLUMN in lowered or (
        "column" in lowered and "does not exist" in lowered
    )


def _probe(db, table: str, columns: Tuple[str, ...]) -> Optional[str]:
    """Ask for these columns. Returns an error string, or None if they are there.

    limit(0) so nothing is transferred: only the column list is being validated,
    and PostgREST validates it before looking at any rows.
    """
    try:
        db.table(table).select(",".join(columns)).limit(0).execute()
        return None
    except Exception as e:
        return str(e)


def _missing_columns(db, table: str, columns: Tuple[str, ...]) -> List[str]:
    """Which of these columns the table does not have, one request each."""
    return [column for column in columns if _probe(db, table, (column,)) is not None]


def check_schema(db=None, expected: Dict[str, Tuple[str, ...]] = None) -> Dict[str, List[str]]:
    """Compare the live database against db/expected_schema.py.

    Returns {table: [missing column, ...]}, with an empty list meaning the whole
    table is missing or unreadable. An empty dict means everything expected is
    present.
    """
    db = db if db is not None else get_supabase_client()
    expected = expected if expected is not None else EXPECTED_SCHEMA

    drift: Dict[str, List[str]] = {}

    for table, columns in expected.items():
        error = _probe(db, table, columns)
        if error is None:
            continue

        if _looks_like_missing_table(error):
            # An empty list means the table itself is gone. Narrowing columns
            # here would report every one of them as missing, which reads as a
            # dozen separate problems instead of one.
            drift[table] = []
            continue

        if not _looks_like_missing_column(error):
            # A timeout or an auth failure is not schema drift, and reporting it
            # as such would send someone hunting for a migration that is fine.
            logger.warning("Schema check could not read %s: %s", table, error)
            continue

        drift[table] = _missing_columns(db, table, columns)

    return drift


def log_schema_drift(drift: Dict[str, List[str]]) -> None:
    if not drift:
        logger.info("Schema check passed: %d table(s) match db/expected_schema.py", len(EXPECTED_SCHEMA))
        return

    for table, missing in sorted(drift.items()):
        if missing:
            logger.error(
                "Schema drift: %s is missing column(s) %s. "
                "A migration in db/migrations/ has probably not been applied here.",
                table, ", ".join(missing),
            )
        else:
            logger.error(
                "Schema drift: table %s is missing or unreadable. "
                "A migration in db/migrations/ has probably not been applied here.",
                table,
            )

    logger.error(
        "Schema check found drift in %d table(s). Run `python scripts/migrate.py --status` "
        "to see what is pending, and `python scripts/audit_schema_usage.py` for the full picture.",
        len(drift),
    )


async def run_schema_check() -> Dict[str, List[str]]:
    """Run the check off the event loop and log the result.

    One request per table, so this is dozens of round trips - worth keeping out
    of the startup path. Callers should fire it as a task rather than await it.
    """
    try:
        drift = await asyncio.to_thread(check_schema)
    except Exception as e:
        logger.error("Schema check itself failed: %s", e, exc_info=True)
        return {}

    log_schema_drift(drift)
    return drift
