"""
Tests for freemium tier-gating: api/deps.py's get_tenant_features/require_feature/
tenant_has_feature, the SellerMenuHandler bot-side gate, and the subscription
date-rollover bug fix in services/multi_tenant_orchestrator.py.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from api.deps import get_current_tenant, get_tenant_features, require_feature, tenant_has_feature
from services.multi_tenant_orchestrator import MultiTenantOrchestrator, _add_one_month
from services.whatsapp.handlers.seller import SellerMenuHandler


FREE_FEATURES = {
    "bot_enabled": True,
    "conversational_dashboard": False,
    "loyalty_system": False,
    "analytics": False,
    "external_integrations": False,
    "multi_language": False,
    "advanced_recommendations": False,
}
PREMIUM_FEATURES = {k: True for k in FREE_FEATURES}


# Minimal app exercising require_feature() as a real FastAPI dependency,
# mirroring how it's wired into api/v1/vendly_pro.py routes.
app = FastAPI()


@app.get("/loyalty-thing")
async def loyalty_thing(
    tenant: dict = Depends(get_current_tenant),
    _features: dict = Depends(require_feature("loyalty_system"))
):
    return {"ok": True}


@app.get("/analytics-thing")
async def analytics_thing(
    tenant: dict = Depends(get_current_tenant),
    _features: dict = Depends(require_feature("analytics"))
):
    return {"ok": True}


client = TestClient(app)


class TestRequireFeatureDependency:
    """require_feature(...) wired as a real FastAPI Depends()."""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_free_tenant_blocked_from_loyalty_route(self):
        app.dependency_overrides[get_current_tenant] = lambda: {"id": "tenant-free"}
        app.dependency_overrides[get_tenant_features] = lambda: FREE_FEATURES

        response = client.get("/loyalty-thing")

        assert response.status_code == 403
        detail = response.json()["detail"]
        assert detail["feature"] == "loyalty_system"
        assert detail["upgrade_required"] is True

    def test_free_tenant_blocked_from_analytics_route(self):
        app.dependency_overrides[get_current_tenant] = lambda: {"id": "tenant-free"}
        app.dependency_overrides[get_tenant_features] = lambda: FREE_FEATURES

        response = client.get("/analytics-thing")

        assert response.status_code == 403
        assert response.json()["detail"]["feature"] == "analytics"

    def test_premium_tenant_passes_through(self):
        app.dependency_overrides[get_current_tenant] = lambda: {"id": "tenant-premium"}
        app.dependency_overrides[get_tenant_features] = lambda: PREMIUM_FEATURES

        loyalty_response = client.get("/loyalty-thing")
        analytics_response = client.get("/analytics-thing")

        assert loyalty_response.status_code == 200
        assert analytics_response.status_code == 200

    def test_missing_subscription_row_fails_safe_to_free(self):
        """No get_tenant_features override here - exercises the real
        _resolve_tenant_features fallback when MultiTenantOrchestrator finds
        no subscription row for the tenant."""
        app.dependency_overrides[get_current_tenant] = lambda: {"id": "tenant-no-subscription"}

        with patch.object(
            MultiTenantOrchestrator, "get_tenant_subscription", new=AsyncMock(return_value=None)
        ):
            response = client.get("/loyalty-thing")

        assert response.status_code == 403


class TestResolveTenantFeatures:
    """Unit-level coverage of get_tenant_features/tenant_has_feature's fallback logic."""

    @pytest.mark.asyncio
    async def test_missing_subscription_defaults_to_free_features(self):
        with patch.object(
            MultiTenantOrchestrator, "get_tenant_subscription", new=AsyncMock(return_value=None)
        ):
            features = await get_tenant_features({"id": "tenant-x"})

        assert features["loyalty_system"] is False
        assert features["analytics"] is False
        assert features["bot_enabled"] is True  # core bot must never be gated

    @pytest.mark.asyncio
    async def test_existing_subscription_features_used_as_is(self):
        with patch.object(
            MultiTenantOrchestrator,
            "get_tenant_subscription",
            new=AsyncMock(return_value={"features": PREMIUM_FEATURES}),
        ):
            features = await get_tenant_features({"id": "tenant-premium"})

        assert features == PREMIUM_FEATURES

    @pytest.mark.asyncio
    async def test_tenant_has_feature_true_and_false(self):
        with patch.object(
            MultiTenantOrchestrator,
            "get_tenant_subscription",
            new=AsyncMock(return_value={"features": FREE_FEATURES}),
        ):
            assert await tenant_has_feature("tenant-x", "loyalty_system") is False
            assert await tenant_has_feature("tenant-x", "bot_enabled") is True


class TestSellerHandlerGating:
    """SellerMenuHandler gates the WhatsApp-side conversational dashboard commands."""

    @pytest.mark.asyncio
    async def test_dashboard_command_blocked_for_free_tier(self):
        handler = SellerMenuHandler(db=MagicMock())

        with patch(
            "services.whatsapp.handlers.seller.tenant_has_feature",
            new=AsyncMock(return_value=False),
        ):
            response = await handler.handle({
                "tenant_id": "tenant-free",
                "phone": "+1234567890",
                "message": "resumen",
                "is_seller": True,
            })

        assert response is not None
        assert "premium" in response.lower()

    @pytest.mark.asyncio
    async def test_dashboard_command_allowed_for_premium_tier(self):
        handler = SellerMenuHandler(db=MagicMock())

        with patch(
            "services.whatsapp.handlers.seller.tenant_has_feature",
            new=AsyncMock(return_value=True),
        ), patch.object(
            handler.dashboard, "process_seller_command", new=AsyncMock(return_value="resumen: 5 pedidos hoy")
        ):
            response = await handler.handle({
                "tenant_id": "tenant-premium",
                "phone": "+1234567890",
                "message": "resumen",
                "is_seller": True,
            })

        assert response == "resumen: 5 pedidos hoy"


class TestSubscriptionDateRollover:
    """Regression coverage for the December/month-end crash fixed in
    services/multi_tenant_orchestrator.py::_create_subscription."""

    def test_december_rolls_over_to_next_year(self):
        assert _add_one_month(datetime(2026, 12, 15)) == datetime(2027, 1, 15)

    def test_month_end_day_is_clamped(self):
        assert _add_one_month(datetime(2026, 1, 31)) == datetime(2026, 2, 28)

    def test_leap_year_february(self):
        assert _add_one_month(datetime(2024, 1, 31)) == datetime(2024, 2, 29)
