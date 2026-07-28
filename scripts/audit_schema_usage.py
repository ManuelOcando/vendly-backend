#!/usr/bin/env python3
"""
Cross-check the columns this codebase asks for against the ones the database has.

    python scripts/audit_schema_usage.py             # report findings, exit 1 if any
    python scripts/audit_schema_usage.py --quiet     # only the summary line

Why this exists: on 2026-07-27 an audit found 41 query chains naming columns or
tables that do not exist. Every one sat inside a try/except, so they did not
crash - the feature simply never happened. Whole endpoints returned 500 or a
hardcoded "disconnected", the seller never received an alert, and 618 passing
tests noticed nothing, because the test doubles model the shape of the query
builder rather than the schema of the database.

Requires DATABASE_URL (Supabase dashboard -> Project Settings -> Database ->
Connection string -> URI), the same variable scripts/migrate.py uses.

What it catches
---------------
* a column that does not exist on the table being queried
* `select("count")` and `select("sum(x)")` - PostgREST reads those as column
  names, not aggregates, and Postgres answers 42703. The aggregate spelling is
  `count()` / `col.sum()`
* `.group()` / `.group_by()` - neither exists on the query builder, so they
  raise AttributeError

What it does not catch
----------------------
Anything the regexes cannot see: f-string column names, columns built at
runtime, or chains split across a helper function. A clean run means "nothing
obviously wrong", not "proven correct".
"""
import argparse
import io
import os
import re
import sys
import textwrap
import tokenize
from pathlib import Path

try:
    import psycopg
except ImportError:
    sys.exit(
        "psycopg is not installed.\n"
        '  pip install "psycopg[binary]"'
    )

BACKEND_ROOT = Path(__file__).parent.parent
SKIP_DIRS = {".git", "venv", ".venv", "__pycache__", "node_modules"}

# Files whose whole purpose is to contain queries this script should hate.
SKIP_FILES = {"tests/test_fake_supabase_schema.py"}

# `.table("orders")` and `.table(table_name)` alike. Group 1 is set only for a
# literal; a variable leaves it None and the chain is still checked for the
# things that are wrong regardless of which table it hits. An earlier version
# of this script only matched literals, and so missed two live bugs behind a
# `for table_name in tables_to_check` loop.
TABLE = re.compile(r'\.table\(\s*(?:["\']([a-z_]+)["\']|([A-Za-z_][A-Za-z0-9_]*))\s*\)')

SELECT = re.compile(r'\.select\(\s*((?:["\'][^"\']*["\']\s*,?\s*)+)')
FILTER = re.compile(
    r'\.(?:eq|neq|gt|gte|lt|lte|like|ilike|in_|is_|order|contains|not_)\('
    r'\s*["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']'
)
MUTATION = re.compile(r'\.(?:insert|update|upsert)\(\s*\{')
DICT_KEY = re.compile(r'["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']\s*:')
AGGREGATE = re.compile(r'\b(count|sum|avg|min|max)\s*\(')

# Only ever matched inside an already-identified query chain. Searching for it
# across whole files instead flags every `time_match.group(1)` from the re
# module, and every comment that mentions the method.
NO_SUCH_METHOD = re.compile(r'\.(group|group_by)\(')

# Bare aggregate names used where a column belongs. PostgREST resolves these to
# columns and Postgres rejects them.
BARE_AGGREGATES = {"count", "sum", "avg", "min", "max"}


def live_schema(database_url: str) -> dict:
    """{table: [column, ...]} for the public schema, in declaration order.

    Ordered rather than a set so --emit-schema produces a file that reads like
    the table does, and so regenerating it twice yields identical output.
    """
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "ORDER BY table_name, ordinal_position"
            )
            schema = {}
            for table, column in cur.fetchall():
                schema.setdefault(table, []).append(column)
            return schema


def render_expected_schema(schema: dict) -> str:
    """The source of db/expected_schema.py for this schema."""
    body = ['"""']
    body.append("The columns this backend expects each table to have. Generated, not hand-written.")
    body.append("")
    body.append("Regenerate after every migration:")
    body.append("")
    body.append("    python scripts/audit_schema_usage.py --emit-schema")
    body.append("")
    body.append("Two consumers, one source of truth:")
    body.append("")
    body.append("* `db/schema_check.py` compares this against the live database at startup and")
    body.append("  logs whatever is missing, so a migration that never reached an environment is")
    body.append("  visible in that environment's boot log instead of surfacing weeks later as a")
    body.append("  feature that quietly does nothing.")
    body.append("* `tests/fake_supabase.py` validates column names against it, so a query naming")
    body.append("  a column that does not exist fails in the test suite rather than in production.")
    body.append("")
    body.append("The second one is the point. Until now the test doubles modelled the shape of")
    body.append("the query builder and not the schema of the database, so a query could be")
    body.append('structurally valid and semantically impossible - `select("count")`,')
    body.append("`orders.total_amount`, `categories.order` - and 618 tests would still pass. An")
    body.append("audit on 2026-07-27 found 41 such queries, every one of them inside a try/except")
    body.append("that turned a schema error into a silently missing feature.")
    body.append('"""')
    body.append("")
    body.append("EXPECTED_SCHEMA = {")

    for table in sorted(schema):
        joined = ", ".join(f'"{column}"' for column in schema[table])
        wrapped = textwrap.wrap(
            joined, width=72,
            initial_indent=" " * 8, subsequent_indent=" " * 8,
            break_long_words=False, break_on_hyphens=False,
        )
        body.append(f'    "{table}": (')
        body.extend(wrapped)
        body.append("    ),")

    body.append("}")
    body.append("")
    body.append("")
    body.append("def columns_for(table: str) -> frozenset:")
    body.append('    """Known columns for a table, or an empty set if it is not in the map."""')
    body.append("    return frozenset(EXPECTED_SCHEMA.get(table, ()))")
    body.append("")
    body.append("")
    body.append("def known_table(table: str) -> bool:")
    body.append("    return table in EXPECTED_SCHEMA")
    body.append("")

    return "\n".join(body)


def python_files() -> list:
    """Every .py file in the backend, except this one.

    Skipping itself matters: the patterns below contain the very strings they
    look for, so it would report its own regex definitions as findings.
    """
    here = Path(__file__).resolve()
    found = []
    for path in BACKEND_ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.resolve() == here:
            continue
        if path.relative_to(BACKEND_ROOT).as_posix() in SKIP_FILES:
            continue
        found.append(path)
    return sorted(found)


def without_comments(source: str) -> str:
    """Blank out comments, keeping every byte offset where it was.

    Prose describing a bug reads exactly like the bug. Without this, a comment
    saying `this used to call .group("tier")` is reported as a finding, and so
    is a commented-out `db.table("loyalty_rewards")`. Offsets are preserved by
    overwriting with spaces so reported line numbers stay correct.

    Docstrings are left alone - they are string tokens, not comments - so a
    docstring quoting a bad query can still produce a false positive.
    """
    lines = source.splitlines(keepends=True)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return source

    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        index = token.start[0] - 1
        start_column, end_column = token.start[1], token.end[1]
        line = lines[index]
        lines[index] = line[:start_column] + " " * (end_column - start_column) + line[end_column:]

    return "".join(lines)


def top_level_keys(text: str) -> set:
    """Keys of the outermost dict in `text`, ignoring nested ones.

    Nested keys are not columns: `update({"migration_data": json.dumps({...,
    "status": x})})` writes one column, and an earlier version of this script
    reported that inner "status" as a missing column.
    """
    keys, depth, index = set(), 0, 0
    while index < len(text):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                break
        elif depth == 1:
            match = DICT_KEY.match(text, index)
            if match:
                keys.add(match.group(1))
                index = match.end()
                continue
        index += 1
    return keys


def columns_in_chain(chunk: str) -> tuple:
    """(columns asked for, aggregate-shaped strings) found in one query chain."""
    columns, aggregates = set(), set()

    for match in SELECT.finditer(chunk):
        for quoted in re.findall(r'["\']([^"\']*)["\']', match.group(1)):
            for piece in quoted.split(","):
                piece = piece.strip()
                if not piece or piece == "*":
                    continue
                # An embedded resource - items(name, price) - is a join, not a
                # column of this table.
                if AGGREGATE.search(piece):
                    aggregates.add(piece)
                elif "(" in piece:
                    continue
                elif piece in BARE_AGGREGATES:
                    aggregates.add(piece)
                else:
                    columns.add(piece)

    columns.update(FILTER.findall(chunk))

    for match in MUTATION.finditer(chunk):
        columns.update(top_level_keys(chunk[match.end() - 1:]))

    return columns, aggregates


def audit(schema: dict) -> list:
    findings = []

    for path in python_files():
        source = without_comments(path.read_text(encoding="utf-8", errors="replace"))
        relative = path.relative_to(BACKEND_ROOT).as_posix()

        for match in TABLE.finditer(source):
            table = match.group(1)
            line = source[:match.start()].count("\n") + 1

            chunk = source[match.end():match.end() + 900]
            end = chunk.find(".execute()")
            if end != -1:
                chunk = chunk[:end]

            columns, aggregates = columns_in_chain(chunk)

            problems = [
                f'"{aggregate}" is read as a column name, not an aggregate'
                for aggregate in sorted(aggregates)
            ]
            problems += [
                f".{method}() does not exist on the query builder"
                for method in sorted({m.group(1) for m in NO_SUCH_METHOD.finditer(chunk)})
            ]

            # A variable table name cannot be resolved statically, so only the
            # table-independent problems above are reported for it.
            if table is not None:
                if table not in schema:
                    problems.append(f"table {table} does not exist")
                else:
                    problems += [
                        f"no column {column}"
                        for column in sorted(columns - set(schema[table]))
                    ]

            if problems:
                findings.append((relative, line, table or "<variable>", problems))

    return sorted(findings)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check the columns the code asks for against the live schema."
    )
    parser.add_argument("--quiet", action="store_true",
                        help="print only the summary line")
    parser.add_argument("--emit-schema", action="store_true",
                        help="regenerate db/expected_schema.py from the live database "
                             "and exit; run this after applying a migration")
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
        return 2

    try:
        schema = live_schema(database_url)
    except Exception as e:
        print(f"Could not read the schema: {e}", file=sys.stderr)
        return 2

    if args.emit_schema:
        target = BACKEND_ROOT / "db" / "expected_schema.py"
        target.write_text(render_expected_schema(schema), encoding="utf-8")
        print(
            f"Wrote {target.relative_to(BACKEND_ROOT).as_posix()}: "
            f"{len(schema)} table(s), {sum(len(c) for c in schema.values())} column(s)."
        )
        return 0

    findings = audit(schema)

    if not args.quiet:
        for relative, line, table, problems in findings:
            print(f"{relative}:{line}  [{table}]")
            for problem in problems:
                print(f"    {problem}")

    print(
        f"\n{len(findings)} finding(s) across {len(python_files())} file(s), "
        f"{len(schema)} table(s) in the live schema."
    )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
