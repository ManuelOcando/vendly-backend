"""
Unit tests for MetaWhatsAppService.for_tenant.

The bug behind it: several services built MetaWhatsAppService() with no
arguments. That constructor falls back to META_WHATSAPP_PHONE_ID and
META_WHATSAPP_TOKEN, so in a multi-tenant backend every message would have gone
out from whichever business those globals belong to.
"""
import pytest
from unittest.mock import Mock

from services.whatsapp.meta_service import MetaWhatsAppService

TENANT = "tenant-abc"


def db_returning(rows, raises=False):
    """A Supabase client stand-in for one whatsapp_configs lookup."""
    db = Mock()
    chain = db.table.return_value.select.return_value.eq.return_value.limit.return_value
    if raises:
        chain.execute.side_effect = RuntimeError("connection reset")
    else:
        chain.execute.return_value = Mock(data=rows)
    return db


class TestForTenant:
    def test_returns_a_service_with_the_tenant_credentials(self, monkeypatch):
        # The globals are set to something different on purpose: a passing test
        # here must prove the tenant's values won, not the environment's.
        monkeypatch.setenv("META_WHATSAPP_PHONE_ID", "global-phone")
        monkeypatch.setenv("META_WHATSAPP_TOKEN", "global-token")

        service = MetaWhatsAppService.for_tenant(
            db_returning([{"phone_number_id": "tenant-phone", "access_token": "tenant-token"}]),
            TENANT,
        )

        assert service.phone_number_id == "tenant-phone"
        assert service.access_token == "tenant-token"

    def test_queries_the_right_tenant(self):
        db = db_returning([{"phone_number_id": "p", "access_token": "t"}])

        MetaWhatsAppService.for_tenant(db, TENANT)

        db.table.assert_called_with("whatsapp_configs")
        db.table.return_value.select.return_value.eq.assert_called_with("tenant_id", TENANT)

    def test_no_config_row_returns_none(self):
        assert MetaWhatsAppService.for_tenant(db_returning([]), TENANT) is None

    @pytest.mark.parametrize("row", [
        {"phone_number_id": "p", "access_token": None},
        {"phone_number_id": None, "access_token": "t"},
        {"phone_number_id": "", "access_token": ""},
        {},
    ])
    def test_incomplete_config_returns_none(self, row, monkeypatch):
        # None rather than a service backed by the global variables: not sending
        # is better than sending from another business's number.
        monkeypatch.setenv("META_WHATSAPP_PHONE_ID", "global-phone")
        monkeypatch.setenv("META_WHATSAPP_TOKEN", "global-token")

        assert MetaWhatsAppService.for_tenant(db_returning([row]), TENANT) is None

    def test_a_database_failure_returns_none_and_does_not_raise(self):
        # Callers treat None as "cannot message this tenant"; raising here would
        # take down a background remarketing run over one bad lookup.
        assert MetaWhatsAppService.for_tenant(db_returning(None, raises=True), TENANT) is None

    def test_logs_at_error_when_the_tenant_cannot_be_messaged(self, caplog):
        with caplog.at_level("ERROR"):
            MetaWhatsAppService.for_tenant(db_returning([]), TENANT)

        assert any(TENANT in r.getMessage() for r in caplog.records if r.levelname == "ERROR")


class TestConstructorFallbackStillExists:
    def test_explicit_arguments_win_over_the_environment(self, monkeypatch):
        monkeypatch.setenv("META_WHATSAPP_PHONE_ID", "global-phone")

        service = MetaWhatsAppService(phone_number_id="explicit", access_token="tok")

        assert service.phone_number_id == "explicit"

    def test_no_arguments_falls_back_to_the_environment(self, monkeypatch):
        # Kept for single-tenant scripts and local testing. This is the behaviour
        # that made the per-tenant bug invisible, so it is pinned here to
        # document that it is intentional and not accidental.
        monkeypatch.setenv("META_WHATSAPP_PHONE_ID", "global-phone")
        monkeypatch.setenv("META_WHATSAPP_TOKEN", "global-token")

        service = MetaWhatsAppService()

        assert service.phone_number_id == "global-phone"
        assert service.access_token == "global-token"
