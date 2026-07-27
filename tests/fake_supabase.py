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
"""
from typing import Any, Dict, List, Optional
import uuid


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

    def select(self, *_columns, **_kwargs):
        # Column projection is ignored on purpose: callers only ever read
        # keys they asked for, and returning whole rows keeps the fake
        # simple without changing any assertion.
        self._operation = "select"
        return self

    def insert(self, payload: Dict[str, Any]):
        self._operation = "insert"
        self._payload = payload
        return self

    def update(self, payload: Dict[str, Any]):
        self._operation = "update"
        self._payload = payload
        return self

    def delete(self):
        self._operation = "delete"
        return self

    # -- filters -----------------------------------------------------------

    def eq(self, column: str, value: Any):
        self._filters.append((column, "eq", value))
        return self

    def neq(self, column: str, value: Any):
        self._filters.append((column, "neq", value))
        return self

    def gte(self, column: str, value: Any):
        self._filters.append((column, "gte", value))
        return self

    def lte(self, column: str, value: Any):
        self._filters.append((column, "lte", value))
        return self

    def lt(self, column: str, value: Any):
        self._filters.append((column, "lt", value))
        return self

    def gt(self, column: str, value: Any):
        self._filters.append((column, "gt", value))
        return self

    def is_(self, column: str, value: Any):
        # supabase spells SQL NULL as the string "null"
        self._filters.append((column, "is", None if value == "null" else value))
        return self

    def in_(self, column: str, values: List[Any]):
        self._filters.append((column, "in", list(values)))
        return self

    def order(self, column: str, desc: bool = False, **_kwargs):
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
            created = dict(self._payload)
            created.setdefault("id", str(uuid.uuid4()))
            rows.append(created)
            return _Result([dict(created)])

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
