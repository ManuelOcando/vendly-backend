#!/usr/bin/env python3
"""
Database migration runner.

Applies every .sql file in db/migrations/ that hasn't been applied yet, in
filename order, each inside its own transaction, and records what ran in a
`schema_migrations` table. Running it twice is a no-op the second time.

    python scripts/migrate.py            # apply pending migrations
    python scripts/migrate.py --status   # show what's applied vs pending
    python scripts/migrate.py --dry-run  # list what would run, change nothing

Requires DATABASE_URL (Supabase dashboard -> Project Settings -> Database ->
Connection string -> URI). The app itself never uses this: it talks to the
database through the Supabase REST client. Only this script needs direct SQL
access, because DDL cannot go through PostgREST.

This replaces scripts/apply_vendly_pro_migration.py, which tried to apply
migrations via `supabase.rpc('exec_sql', ...)` - a function that does not
exist in the project. It could never have worked, and its failure was silent
enough that migrations 009-013 were never applied to production.
"""
import argparse
import os
import sys
from pathlib import Path

try:
    import psycopg
except ImportError:
    sys.exit(
        "psycopg is not installed.\n"
        '  pip install "psycopg[binary]"'
    )

BACKEND_ROOT = Path(__file__).parent.parent
MIGRATIONS_DIR = BACKEND_ROOT / "db" / "migrations"

# The error message below tells the reader to put DATABASE_URL in .env, so read
# it. Without this the script only ever saw real environment variables and told
# people to do something that did nothing.
try:
    from dotenv import load_dotenv

    load_dotenv(BACKEND_ROOT / ".env")
except ImportError:
    pass

CREATE_TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def migration_files() -> list:
    """Every migration on disk, in filename order (001_, 002_, ...)."""
    return sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda path: path.name)


def applied_migrations(conn) -> set:
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def apply_migration(conn, path: Path) -> None:
    """Run one migration and record it, atomically.

    The whole file plus its bookkeeping row commit together, so a failure
    leaves no partial record - the migration stays pending and can be
    retried once fixed.
    """
    sql = path.read_text(encoding="utf-8")
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)",
                (path.name,),
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply pending database migrations.")
    parser.add_argument("--status", action="store_true",
                        help="show applied and pending migrations, change nothing")
    parser.add_argument("--dry-run", action="store_true",
                        help="list what would be applied, change nothing")
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print(
            "DATABASE_URL is not set.\n\n"
            "Get it from the Supabase dashboard:\n"
            "  Project Settings -> Database -> Connection string -> URI\n\n"
            "Then either export it:\n"
            '  export DATABASE_URL="postgresql://..."\n'
            "or add it to vendly-backend/.env",
            file=sys.stderr,
        )
        return 1

    on_disk = migration_files()
    if not on_disk:
        print(f"No migrations found in {MIGRATIONS_DIR}")
        return 0

    try:
        conn = psycopg.connect(database_url)
    except Exception as e:
        print(f"Could not connect to the database: {e}", file=sys.stderr)
        return 1

    with conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TRACKING_TABLE)
        conn.commit()

        done = applied_migrations(conn)
        pending = [path for path in on_disk if path.name not in done]

        if args.status:
            print(f"Applied ({len(done)}):")
            for path in on_disk:
                if path.name in done:
                    print(f"  [x] {path.name}")
            print(f"\nPending ({len(pending)}):")
            for path in pending:
                print(f"  [ ] {path.name}")
            return 0

        if not pending:
            print(f"Up to date - {len(done)} migration(s) already applied.")
            return 0

        print(f"{len(pending)} migration(s) pending:")
        for path in pending:
            print(f"  - {path.name}")

        if args.dry_run:
            print("\nDry run: nothing was applied.")
            return 0

        print()
        failed = None
        for path in pending:
            print(f"Applying {path.name} ... ", end="", flush=True)
            try:
                apply_migration(conn, path)
                print("OK")
            except Exception as e:
                print("FAILED")
                print(f"\n  {type(e).__name__}: {e}\n", file=sys.stderr)
                failed = path
                break

        if failed:
            remaining = pending[pending.index(failed):]
            print(
                f"Stopped at {failed.name}. {len(remaining)} migration(s) still pending.\n"
                "Nothing from the failed migration was committed - fix it and re-run.",
                file=sys.stderr,
            )
            return 1

        print(f"\nApplied {len(pending)} migration(s).")
        return 0


if __name__ == "__main__":
    sys.exit(main())
