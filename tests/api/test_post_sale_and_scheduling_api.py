"""
Tests for the Post-Sale Support and Service Scheduling REST endpoints
(api/v1/post_sale.py, api/v1/scheduling.py).
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, AsyncMock

from api.v1.post_sale import router as post_sale_router
from api.v1.scheduling import router as scheduling_router
from api.deps import get_current_tenant

app = FastAPI()
app.include_router(post_sale_router, prefix="/api/v1")
app.include_router(scheduling_router, prefix="/api/v1")

MOCK_TENANT = {"id": "tenant-123", "name": "Test Tenant"}


@pytest.fixture(autouse=True)
def override_tenant_dependency():
    app.dependency_overrides[get_current_tenant] = lambda: MOCK_TENANT
    yield
    app.dependency_overrides.pop(get_current_tenant, None)


@pytest.fixture
def client():
    return TestClient(app)


class TestPostSaleRequestsAPI:
    def test_list_requests_returns_data(self, client):
        mock_db = Mock()
        mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = Mock(
            data=[{"id": "req-1", "status": "open"}]
        )

        with patch("api.v1.post_sale.get_supabase_client", return_value=mock_db):
            response = client.get("/api/v1/post-sale-requests")

        assert response.status_code == 200
        assert response.json() == [{"id": "req-1", "status": "open"}]

    def test_list_requests_filters_by_status(self, client):
        mock_db = Mock()
        chain = mock_db.table.return_value.select.return_value.eq.return_value
        chain.eq.return_value.order.return_value.limit.return_value.execute.return_value = Mock(
            data=[{"id": "req-2", "status": "resolved"}]
        )

        with patch("api.v1.post_sale.get_supabase_client", return_value=mock_db):
            response = client.get("/api/v1/post-sale-requests?status=resolved")

        assert response.status_code == 200
        assert response.json() == [{"id": "req-2", "status": "resolved"}]

    def test_resolve_request_success(self, client):
        with patch("api.v1.post_sale.PostSaleService") as mock_service_cls:
            mock_service_cls.return_value.resolve_request = AsyncMock(return_value=True)
            response = client.put("/api/v1/post-sale-requests/req-1/resolve")

        assert response.status_code == 200
        mock_service_cls.return_value.resolve_request.assert_awaited_once_with("tenant-123", "req-1")

    def test_resolve_request_not_found(self, client):
        with patch("api.v1.post_sale.PostSaleService") as mock_service_cls:
            mock_service_cls.return_value.resolve_request = AsyncMock(return_value=False)
            response = client.put("/api/v1/post-sale-requests/missing/resolve")

        assert response.status_code == 404


class TestAppointmentsAPI:
    def test_available_slots_returns_isoformatted_times(self, client):
        from datetime import datetime
        slot = datetime(2026, 8, 1, 9, 0)

        with patch("api.v1.scheduling.SchedulingService") as mock_service_cls:
            mock_service_cls.return_value.get_available_slots = AsyncMock(return_value=[slot])
            response = client.get(
                "/api/v1/appointments/available-slots",
                params={"item_id": "svc-1", "date": "2026-08-01"},
            )

        assert response.status_code == 200
        assert response.json() == {"slots": [slot.isoformat()]}

    def test_available_slots_invalid_date_rejected(self, client):
        response = client.get(
            "/api/v1/appointments/available-slots",
            params={"item_id": "svc-1", "date": "not-a-date"},
        )
        assert response.status_code == 400

    def test_list_appointments_returns_data(self, client):
        mock_db = Mock()
        mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = Mock(
            data=[{"id": "appt-1", "status": "scheduled"}]
        )

        with patch("api.v1.scheduling.get_supabase_client", return_value=mock_db):
            response = client.get("/api/v1/appointments")

        assert response.status_code == 200
        assert response.json() == [{"id": "appt-1", "status": "scheduled"}]

    def test_cancel_appointment_success(self, client):
        with patch("api.v1.scheduling.SchedulingService") as mock_service_cls:
            mock_service_cls.return_value.cancel_appointment = AsyncMock(
                return_value={"success": True, "message": "Tu cita fue cancelada."}
            )
            response = client.put(
                "/api/v1/appointments/appt-1/cancel", json={"reason": "no puedo asistir"}
            )

        assert response.status_code == 200
        mock_service_cls.return_value.cancel_appointment.assert_awaited_once_with(
            "tenant-123", "appt-1", "no puedo asistir"
        )

    def test_cancel_appointment_blocked_by_policy_returns_400(self, client):
        with patch("api.v1.scheduling.SchedulingService") as mock_service_cls:
            mock_service_cls.return_value.cancel_appointment = AsyncMock(
                return_value={"success": False, "message": "Debes cancelar con 24h de anticipación."}
            )
            response = client.put("/api/v1/appointments/appt-1/cancel", json={})

        assert response.status_code == 400
