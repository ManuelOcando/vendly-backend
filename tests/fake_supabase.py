"""
In-memory stand-in for the Supabase client, for multi-turn integration tests.

The MagicMock-based routers used elsewhere in the suite return canned data
per table, which is fine for single-call unit tests but cannot support a
conversation: turn N+1 has to see what turn N wrote. This fake keeps real
rows in memory so a journey through MetaWhatsAppBotService.process_message
behaves like the real thing.

Patch it in with:

    with patch("db.supabase.create_client", return_value=fake):
        ...

`get_supabase_client` looks `create_client` up in its own module globals at
call time, so that single patch reaches every component that builds its own
client (the bot, MultiTenantOrchestrator inside api/deps.py, PostSaleService
inside the handler, ...). Patching `get_supabase_client` itself would not:
modules import it by name, binding it in their own namespace at import time.

Only the query-builder subset the production code actually uses is
implemented. Anything else raises, so an unsupported call fails loudly
instead of silently returning nothing.

Column names are checked against `db/expected_schema.py`, which is generated
from the real database. That check is the reason this file matters beyond
multi-turn state: it used to ignore the column list entirely, so a query could
be structurally valid and semantically impossible and every test would still
pass. An audit on 2026-07-27 found 41 queries like that - `select("count")`,
`orders.total_amount`, `categories.order` - each one wrapped in a try/except
that turned the resulting error into a feature that quietly did nothing. Two
tests had even encoded the broken shapes in their mocks.
"""
from typing import Any, Dict, List, Optional
import re
import uuid

from db.expected_schema import EXPECTED_SCHEMA


class SchemaError(AssertionError):
    """A query named something the database does not have.

    An AssertionError so it reads as a test failure rather than a bug in the
    fake, which is what it is: production code asking for a column that is not
    there.
    """


# `count`, `sum(x)`, `avg(x)`: PostgREST resolves these to column names and
# Postgres answers 42703. The aggregate spelling is `count()` / `col.sum()`.
_AGGREGATES = {"count", "sum", "avg", "min", "max"}
_AGGREGATE_CALL = re.compile(r"^(count|sum|avg|min|max)\s*\(")

# items(name, price) is an embedded resource - a join - not a column of this
# table, so it is not checked here.
_EMBEDDED = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*\s*\(")


def _split_columns(spec: str) -> List[str]:
    """Split a select list on commas that are not inside parentheses.

    A plain spec.split(",") tears `items(name, price)` into `items(name` and
    `price)`, and then reports `price)` as an unknown column.
    """
    parts, depth, current = [], 0, []
    for char in spec:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def _check_columns(table: str, columns, where: str) -> None:
    """Raise if any of these names is not a column of `table`.

    Tables absent from EXPECTED_SCHEMA are skipped rather than rejected: a test
    is free to invent a table for a fixture, and failing on that would make the
    fake harder to use without catching anything real.
    """
    known = EXPECTED_SCHEMA.get(table)
    if known is None:
        return

    unknown = []
    for column in columns:
        column = column.strip()
        if not column or column == "*":
            continue
        if _AGGREGATE_CALL.match(column):
            raise SchemaError(
                f'{table}: "{column}" in {where} is not supported by PostgREST - '
                f"it reads as a column name and Postgres answers 42703. "
                f"Fetch the rows and aggregate in Python."
            )
        if column in _AGGREGATES:
            raise SchemaError(
                f'{table}: "{column}" in {where} is read as a column name, not an '
                f"aggregate, and Postgres answers 42703. To count rows, select a "
                f"real column and use len(result.data)."
            )
        if _EMBEDDED.match(column):
            continue
        if column not in known:
            unknown.append(column)

    if unknown:
        raise SchemaError(
            f"{table}: no column {', '.join(sorted(unknown))} (in {where}). "
            f"PostgREST rejects the whole query over one unknown column. "
            f"If the column is new, apply the migration and regenerate with "
            f"`python scripts/audit_schema_usage.py --emit-schema`."
        )


class _Result:
    """Mimics the supabase-py APIResponse: just a `.data` list."""

    def __init__(self, data: List[Dict[str, Any]]):
        self.data = data


class _Query:
    """Chainable query builder over a single in-memory table."""

    def __init__(self, store: Dict[str, List[Dict[str, Any]]], table: str):
        self._store = store
        self._table = table
        self._filters = []           # list of (column, op, value)
        self._operation = "select"
        self._payload: Optional[Dict[str, Any]] = None
        self._order: Optional[tuple] = None
        self._limit: Optional[int] = None
        self._range: Optional[tuple] = None

    # -- operations --------------------------------------------------------

    def select(self, *columns, **_kwargs):
        # Whole rows are still returned - callers only read the keys they asked
        # for, and projecting would change no assertion. The names are validated
        # though, which is the part that used to be missing: PostgREST rejects
        # the entire query over one unknown column, and ignoring that here let
        # impossible queries pass the suite for months.
        self._operation = "select"
        for group in columns:
            if isinstance(group, str):
                _check_columns(self._table, _split_columns(group), "select()")
        return self

    def insert(self, payload):
        """Accepts a single row or a list of them, as supabase-py does."""
        self._operation = "insert"
        self._payload = payload
        for row in payload if isinstance(payload, list) else [payload]:
            _check_columns(self._table, row.keys(), "insert()")
        return self

    def update(self, payload: Dict[str, Any]):
        self._operation = "update"
        self._payload = payload
        _check_columns(self._table, payload.keys(), "update()")
        return self

    def delete(self):
        self._operation = "delete"
        return self

    # -- filters -----------------------------------------------------------

    def _filter(self, column: str, op: str, value: Any):
        _check_columns(self._table, [column], f".{op}()")
        self._filters.append((column, op, value))
        return self

    def eq(self, column: str, value: Any):
        return self._filter(column, "eq", value)

    def neq(self, column: str, value: Any):
        return self._filter(column, "neq", value)

    def gte(self, column: str, value: Any):
        return self._filter(column, "gte", value)

    def lte(self, column: str, value: Any):
        return self._filter(column, "lte", value)

    def lt(self, column: str, value: Any):
        return self._filter(column, "lt", value)

    def gt(self, column: str, value: Any):
        return self._filter(column, "gt", value)

    def is_(self, column: str, value: Any):
        # supabase spells SQL NULL as the string "null"
        return self._filter(column, "is", None if value == "null" else value)

    def in_(self, column: str, values: List[Any]):
        return self._filter(column, "in", list(values))

    def order(self, column: str, desc: bool = False, **_kwargs):
        _check_columns(self._table, [column], "order()")
        self._order = (column, desc)
        return self

    def limit(self, count: int):
        self._limit = count
        return self

    def range(self, start: int, end: int):
        # supabase range() is inclusive on both ends
        self._range = (start, end)
        return self

    # -- execution ---------------------------------------------------------

    def _rows(self) -> List[Dict[str, Any]]:
        return self._store.setdefault(self._table, [])

    def _matches(self, row: Dict[str, Any]) -> bool:
        for column, op, value in self._filters:
            actual = row.get(column)
            if op == "eq" and actual != value:
                return False
            if op == "neq" and actual == value:
                return False
            if op == "is" and actual is not value and actual != value:
                return False
            if op == "in" and actual not in value:
                return False
            if op in ("gte", "lte", "lt", "gt"):
                if actual is None:
                    return False
                if op == "gte" and not actual >= value:
                    return False
                if op == "lte" and not actual <= value:
                    return False
                if op == "lt" and not actual < value:
                    return False
                if op == "gt" and not actual > value:
                    return False
        return True

    def execute(self) -> _Result:
        rows = self._rows()

        if self._operation == "insert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            created_rows = []
            for row in payload:
                created = dict(row)
                created.setdefault("id", str(uuid.uuid4()))
                rows.append(created)
                created_rows.append(dict(created))
            return _Result(created_rows)

        matching = [row for row in rows if self._matches(row)]

        if self._operation == "update":
            for row in matching:
                row.update(self._payload)
            return _Result([dict(row) for row in matching])

        if self._operation == "delete":
            for row in matching:
                rows.remove(row)
            return _Result([dict(row) for row in matching])

        # select
        if self._order:
            column, desc = self._order
            matching = sorted(
                matching, key=lambda row: (row.get(column) is None, row.get(column)), reverse=desc
            )
        if self._range is not None:
            start, end = self._range
            matching = matching[start : end + 1]
        if self._limit is not None:
            matching = matching[: self._limit]
        return _Result([dict(row) for row in matching])


class FakeSupabaseClient:
    """Drop-in replacement for the supabase Client used by the backend."""

    def __init__(self, tables: Optional[Dict[str, List[Dict[str, Any]]]] = None):
        self.tables: Dict[str, List[Dict[str, Any]]] = tables or {}

    def table(self, name: str) -> _Query:
        return _Query(self.tables, name)

    def rpc(self, _name: str, _params: Optional[Dict[str, Any]] = None):
        """Stored procedures aren't modelled; callers (the recommendation
        engine's affinity lookup) already degrade gracefully on failure."""
        return _Query({}, "__rpc__")

    # -- test helpers ------------------------------------------------------

    def rows(self, table: str) -> List[Dict[str, Any]]:
        """Direct read of a table, for assertions."""
        return self.tables.setdefault(table, [])

    def insert_row(self, table: str, row: Dict[str, Any]) -> Dict[str, Any]:
        row.setdefault("id", str(uuid.uuid4()))
        self.tables.setdefault(table, []).append(row)
        return row


FREE_FEATURES = {
    "bot_enabled": True,
    "conversational_dashboard": False,
    "loyalty_system": False,
    "analytics": False,
    "external_integrations": False,
    "multi_language": False,
    "advanced_recommendations": False,
}

PREMIUM_FEATURES = {key: True for key in FREE_FEATURES}

TENANT_ID = "tenant-e2e"
SELLER_PHONE = "+5550000001"
CUSTOMER_PHONE = "+5550000002"


def seed_tenant(
    tier: str = "premium",
    default_language: str = "es",
    business_hours: Optional[Dict[str, Any]] = None,
    items: Optional[List[Dict[str, Any]]] = None,
) -> FakeSupabaseClient:
    """Build a fake DB holding one fully-configured tenant.

    `business_hours` defaults to {} which means "not configured", and
    OfflineModeService fail-opens on that - so journeys are online unless a
    test explicitly closes the shop.
    """
    features = PREMIUM_FEATURES if tier == "premium" else FREE_FEATURES

    fake = FakeSupabaseClient({
        "tenants": [{
            "id": TENANT_ID,
            "name": "Mi Tienda",
            "onboarding_status": "completed",
        }],
        "whatsapp_configs": [{
            "id": "config-1",
            "tenant_id": TENANT_ID,
            "seller_phone": SELLER_PHONE,
            "phone_number": SELLER_PHONE,
            "phone_number_id": "phone-id-1",
            "access_token": "token-1",
        }],
        "bot_configurations": [{
            "id": "bot-config-1",
            "tenant_id": TENANT_ID,
            "business_hours": business_hours if business_hours is not None else {},
            "auto_reply_enabled": True,
            "bot_paused": False,
            "timezone": "America/Caracas",
            "default_language": default_language,
        }],
        "tenant_subscriptions": [{
            "id": "sub-1",
            "tenant_id": TENANT_ID,
            "plan_type": tier,
            "status": "active",
            "features": features,
            "created_at": "2026-01-01T00:00:00",
        }],
        "items": items if items is not None else [
            {
                "id": "item-1", "tenant_id": TENANT_ID, "name": "Hamburguesa",
                "price": 10.0, "description": "Con queso", "is_active": True,
            },
            {
                "id": "item-2", "tenant_id": TENANT_ID, "name": "Papas",
                "price": 4.5, "description": "Crocantes", "is_active": True,
            },
        ],
        "conversation_sessions": [],
        "whatsapp_messages": [],
        "orders": [],
        "offline_messages": [],
        "business_hours_exceptions": [],
        "post_sale_requests": [],
        "customer_profiles": [],
        "purchase_history": [],
    })
    return fake
