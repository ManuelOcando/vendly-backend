"""
Tests for the Advanced Analytics REST endpoints (api/v1/analytics.py).
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

from api.v1.analytics import router as analytics_router
from api.deps import get_current_tenant, get_tenant_features

app = FastAPI()
app.include_router(analytics_router, prefix="/api/v1")

MOCK_TENANT = {"id": "tenant-123", "name": "Test Tenant"}
ANALYTICS_ENABLED = {"analytics": True}
ANALYTICS_DISABLED = {"analytics": False}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def override_tenant_dependency():
    app.dependency_overrides[get_current_tenant] = lambda: MOCK_TENANT
    app.dependency_overrides[get_tenant_features] = lambda: ANALYTICS_ENABLED
    yield
    app.dependency_overrides.pop(get_current_tenant, None)
    app.dependency_overrides.pop(get_tenant_features, None)


class TestAnalyticsEndpoints:
    def test_conversion_rate_returns_service_data(self, client):
        with patch("api.v1.analytics.AdvancedAnalyticsService") as mock_service_cls:
            mock_service_cls.return_value.get_conversion_rate = AsyncMock(return_value={
                "period_days": 7, "unique_conversations": 10, "orders_count": 4, "conversion_rate": 0.4,
            })
            response = client.get("/api/v1/analytics/conversion-rate")

        assert response.status_code == 200
        assert response.json()["conversion_rate"] == 0.4
        mock_service_cls.return_value.get_conversion_rate.assert_awaited_once_with("tenant-123", period_days=7)

    def test_conversion_rate_respects_period_days_query_param(self, client):
        with patch("api.v1.analytics.AdvancedAnalyticsService") as mock_service_cls:
            mock_service_cls.return_value.get_conversion_rate = AsyncMock(return_value={})
            client.get("/api/v1/analytics/conversion-rate?period_days=30")

        mock_service_cls.return_value.get_conversion_rate.assert_awaited_once_with("tenant-123", period_days=30)

    def test_response_times_returns_service_data(self, client):
        with patch("api.v1.analytics.AdvancedAnalyticsService") as mock_service_cls:
            mock_service_cls.return_value.get_response_time_metrics = AsyncMock(return_value={
                "avg_response_seconds": 30.0, "max_response_seconds": 90.0, "sample_size": 5,
            })
            response = client.get("/api/v1/analytics/response-times")

        assert response.status_code == 200
        assert response.json()["sample_size"] == 5

    def test_peak_activity_returns_service_data(self, client):
        with patch("api.v1.analytics.AdvancedAnalyticsService") as mock_service_cls:
            mock_service_cls.return_value.get_peak_activity = AsyncMock(return_value={
                "peak_activity_hour": 19,
            })
            response = client.get("/api/v1/analytics/peak-activity")

        assert response.status_code == 200
        assert response.json()["peak_activity_hour"] == 19

    def test_satisfaction_returns_service_data(self, client):
        with patch("api.v1.analytics.AdvancedAnalyticsService") as mock_service_cls:
            mock_service_cls.return_value.get_satisfaction_summary = AsyncMock(return_value={
                "avg_rating": 4.2,
            })
            response = client.get("/api/v1/analytics/satisfaction")

        assert response.status_code == 200
        assert response.json()["avg_rating"] == 4.2

    def test_insights_wraps_list_in_object(self, client):
        with patch("api.v1.analytics.AdvancedAnalyticsService") as mock_service_cls:
            mock_service_cls.return_value.generate_insights = AsyncMock(return_value=["insight 1", "insight 2"])
            response = client.get("/api/v1/analytics/insights")

        assert response.status_code == 200
        assert response.json() == {"insights": ["insight 1", "insight 2"]}

    def test_daily_report_wraps_string_in_object(self, client):
        with patch("api.v1.analytics.AdvancedAnalyticsService") as mock_service_cls:
            mock_service_cls.return_value.generate_daily_report = AsyncMock(return_value="reporte de prueba")
            response = client.get("/api/v1/analytics/daily-report")

        assert response.status_code == 200
        assert response.json() == {"report": "reporte de prueba"}

    def test_weekly_report_wraps_string_in_object(self, client):
        with patch("api.v1.analytics.AdvancedAnalyticsService") as mock_service_cls:
            mock_service_cls.return_value.generate_weekly_report = AsyncMock(return_value="reporte semanal")
            response = client.get("/api/v1/analytics/weekly-report")

        assert response.status_code == 200
        assert response.json() == {"report": "reporte semanal"}


class TestAnalyticsFeatureGating:
    def test_endpoints_reject_tenants_without_analytics_feature(self, client):
        app.dependency_overrides[get_tenant_features] = lambda: ANALYTICS_DISABLED

        response = client.get("/api/v1/analytics/conversion-rate")

        assert response.status_code == 403
