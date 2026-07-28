"""
Unit tests for the startup schema check.

The scenario being guarded: migrations 009-015 existed in db/migrations/ but had
never been applied to the live project, and nothing said so. Features that
needed those tables failed inside their exception handlers for weeks.
"""
import pytest

from db.expected_schema import EXPECTED_SCHEMA
from db.schema_check import check_schema, log_schema_drift


class FakeTable:
    """Minimal PostgREST stand-in that rejects unknown columns the way it does."""

    def __init__(self, table, available):
        self._table = table
        self._available = available
        self._columns = []

    def select(self, columns):
        self._columns = [c.strip() for c in columns.split(",")]
        return self

    def limit(self, _count):
        return self

    def execute(self):
        # These two payloads are copied from what this project's PostgREST
        # actually returns, not invented: a missing table is PGRST205 from the
        # schema cache, not Postgres's 42P01.
        if self._available is None:
            raise RuntimeError(
                "{'message': \"Could not find the table "
                f"'public.{self._table}' in the schema cache\", 'code': 'PGRST205'}}"
            )
        missing = [c for c in self._columns if c not in self._available]
        if missing:
            # PostgREST fails the whole request over one unknown column - the
            # behaviour that made every one of these bugs invisible.
            raise RuntimeError(
                "{'message': 'column "
                f"{self._table}.{missing[0]} does not exist', 'code': '42703'}}"
            )
        return self


class FakeDB:
    def __init__(self, schema):
        self._schema = schema

    def table(self, name):
        return FakeTable(name, self._schema.get(name))


class TimingOutDB:
    def table(self, _name):
        raise RuntimeError("timed out waiting for connection")


class TestCheckSchema:
    def test_matching_schema_reports_no_drift(self):
        expected = {"tenants": ("id", "name"), "orders": ("id", "total")}
        db = FakeDB({"tenants": {"id", "name"}, "orders": {"id", "total"}})

        assert check_schema(db=db, expected=expected) == {}

    def test_extra_columns_in_the_database_are_not_drift(self):
        # The check asks whether what the code needs is present, not whether the
        # database is minimal.
        expected = {"tenants": ("id", "name")}
        db = FakeDB({"tenants": {"id", "name", "logo_url", "created_at"}})

        assert check_schema(db=db, expected=expected) == {}

    def test_a_missing_column_is_named(self):
        # The real case: whatsapp_configs.seller_phone was selected by nine
        # files and did not exist.
        expected = {"whatsapp_configs": ("id", "phone_number", "seller_phone")}
        db = FakeDB({"whatsapp_configs": {"id", "phone_number"}})

        assert check_schema(db=db, expected=expected) == {
            "whatsapp_configs": ["seller_phone"]
        }

    def test_several_missing_columns_are_all_named(self):
        # One request per table would only ever reveal the first bad column, so
        # failures get narrowed down column by column.
        expected = {"tenants": ("id", "type", "bot_personality_preset", "onboarding_status")}
        db = FakeDB({"tenants": {"id", "type"}})

        assert check_schema(db=db, expected=expected) == {
            "tenants": ["bot_personality_preset", "onboarding_status"]
        }

    def test_a_missing_table_reports_an_empty_column_list(self):
        expected = {"coupons": ("id", "coupon_code")}
        db = FakeDB({})

        assert check_schema(db=db, expected=expected) == {"coupons": []}

    def test_one_bad_table_does_not_hide_the_others(self):
        expected = {
            "tenants": ("id",),
            "orders": ("id", "total"),
            "coupons": ("id",),
        }
        db = FakeDB({"tenants": {"id"}, "orders": {"id"}})

        assert check_schema(db=db, expected=expected) == {"orders": ["total"], "coupons": []}

    def test_a_timeout_is_not_reported_as_drift(self):
        # Calling a connection problem "schema drift" sends someone hunting for
        # a migration that is fine.
        expected = {"tenants": ("id", "name")}

        assert check_schema(db=TimingOutDB(), expected=expected) == {}


class TestExpectedSchema:
    def test_the_generated_map_is_not_empty(self):
        assert len(EXPECTED_SCHEMA) > 30

    def test_every_table_declares_columns(self):
        for table, columns in EXPECTED_SCHEMA.items():
            assert columns, f"{table} declares no columns"

    def test_columns_the_audit_found_missing_are_declared(self):
        # These are the exact columns whose absence broke live features; if a
        # regeneration ever drops them the check would stop catching it.
        assert "seller_phone" in EXPECTED_SCHEMA["whatsapp_configs"]
        assert "bot_personality_preset" in EXPECTED_SCHEMA["tenants"]
        assert "sort_order" in EXPECTED_SCHEMA["categories"]
        assert "customer_phone" in EXPECTED_SCHEMA["orders"]
        assert "total" in EXPECTED_SCHEMA["orders"]

    def test_columns_that_never_existed_are_not_declared(self):
        assert "total_amount" not in EXPECTED_SCHEMA["orders"]
        assert "customer_email" not in EXPECTED_SCHEMA["orders"]
        assert "order" not in EXPECTED_SCHEMA["categories"]
        assert "llm_config" not in EXPECTED_SCHEMA["whatsapp_configs"]
        assert "count" not in EXPECTED_SCHEMA["loyalty_points"]


class TestLogSchemaDrift:
    def test_clean_run_logs_at_info(self, caplog):
        with caplog.at_level("INFO"):
            log_schema_drift({})
        assert not [r for r in caplog.records if r.levelname == "ERROR"]

    def test_drift_logs_at_error_and_names_the_columns(self, caplog):
        # ERROR is the point: WARNING is what the old handlers used, and it is
        # what nobody read.
        with caplog.at_level("ERROR"):
            log_schema_drift({"whatsapp_configs": ["seller_phone"]})

        errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
        assert any("whatsapp_configs" in m and "seller_phone" in m for m in errors)

    def test_missing_table_is_reported_differently(self, caplog):
        with caplog.at_level("ERROR"):
            log_schema_drift({"coupons": []})

        errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
        assert any("coupons" in m and "missing or unreadable" in m for m in errors)
