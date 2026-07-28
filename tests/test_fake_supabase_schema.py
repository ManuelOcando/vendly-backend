"""
Tests for the column validation in the test double itself.

If this validation is wrong the whole suite is either blind again or blocked by
false alarms, so it gets its own tests. Every "should raise" case below is a
real bug that shipped and was found by the 2026-07-27 audit.
"""
import pytest

from tests.fake_supabase import FakeSupabaseClient, SchemaError


@pytest.fixture
def fake():
    return FakeSupabaseClient({"orders": [], "categories": [], "order_items": []})


class TestRejectsWhatPostgrestRejects:
    def test_unknown_column_in_select(self, fake):
        # api/v1/customers.py asked for this and returned 500 on every call.
        with pytest.raises(SchemaError, match="customer_email"):
            fake.table("orders").select("customer_name, customer_email").execute()

    def test_unknown_column_in_a_filter(self, fake):
        with pytest.raises(SchemaError, match="no column nope"):
            fake.table("orders").eq("nope", 1).execute()

    def test_unknown_column_in_order(self, fake):
        with pytest.raises(SchemaError, match="no column nope"):
            fake.table("orders").select("id").order("nope").execute()

    def test_unknown_column_in_insert(self, fake):
        # The WhatsApp order confirmation inserted both of these into orders.
        with pytest.raises(SchemaError, match="items"):
            fake.table("orders").insert({"tenant_id": "t", "items": []}).execute()

    def test_unknown_column_in_update(self, fake):
        with pytest.raises(SchemaError, match="no column nope"):
            fake.table("orders").update({"nope": 1}).eq("id", "x").execute()

    def test_unknown_column_in_a_bulk_insert(self, fake):
        with pytest.raises(SchemaError, match="no column nope"):
            fake.table("order_items").insert([
                {"tenant_id": "t", "order_id": "o"},
                {"tenant_id": "t", "nope": 1},
            ]).execute()

    def test_bare_count_is_rejected_with_advice(self, fake):
        # loyalty_service did this in six places; PostgREST answers 42703.
        with pytest.raises(SchemaError, match="len\\(result.data\\)"):
            fake.table("orders").select("count").execute()

    def test_aggregate_call_syntax_is_rejected(self, fake):
        with pytest.raises(SchemaError, match="aggregate in Python"):
            fake.table("orders").select("sum(total)").execute()

    def test_the_renamed_categories_column(self, fake):
        # `order` broke seeding industry categories and saving the first product
        # of a new category; the column is sort_order.
        with pytest.raises(SchemaError, match="no column order"):
            fake.table("categories").insert({"tenant_id": "t", "order": 1}).execute()


class TestAcceptsWhatPostgrestAccepts:
    def test_real_columns(self, fake):
        fake.table("orders").select("id, total, customer_phone").eq("tenant_id", "t").execute()

    def test_star(self, fake):
        fake.table("orders").select("*").execute()

    def test_sort_order_is_fine(self, fake):
        fake.table("categories").insert({"tenant_id": "t", "sort_order": 1}).execute()

    def test_embedded_resources_are_not_treated_as_columns(self, fake):
        # items(name, price) is a join, not a column of orders.
        fake.table("orders").select("id, items(name, price)").execute()

    def test_separate_positional_columns(self, fake):
        # supabase-py takes *columns; only reading the first one hid a real bug.
        fake.table("orders").select("customer_phone", "total", "created_at").execute()

    def test_unknown_tables_are_skipped_not_rejected(self, fake):
        # A test is free to invent a table for a fixture; rejecting that would
        # make the fake annoying without catching anything real.
        fake.table("una_tabla_de_prueba").insert({"cualquier_cosa": 1}).execute()

    def test_bulk_insert_of_valid_rows_returns_them_all(self, fake):
        result = fake.table("order_items").insert([
            {"tenant_id": "t", "order_id": "o", "item_name": "A", "quantity": 1},
            {"tenant_id": "t", "order_id": "o", "item_name": "B", "quantity": 2},
        ]).execute()

        assert len(result.data) == 2
        assert len(fake.rows("order_items")) == 2


class TestErrorMessagesAreActionable:
    def test_mentions_the_table_and_the_clause(self, fake):
        with pytest.raises(SchemaError) as excinfo:
            fake.table("orders").select("total_amount").execute()

        message = str(excinfo.value)
        assert "orders" in message
        assert "select()" in message
        assert "total_amount" in message

    def test_points_at_how_to_regenerate_the_schema(self, fake):
        # A genuinely new column means the map is stale, not the code wrong.
        with pytest.raises(SchemaError, match="--emit-schema"):
            fake.table("orders").select("columna_nueva").execute()
