"""
Unit tests for PostSaleService (spec requirement 19).
"""
import pytest
from unittest.mock import Mock, MagicMock, patch

from services.post_sale_service import PostSaleService
from db.token_crypto import encrypt_token


def make_table_router(canned: dict):
    def _table(name):
        m = MagicMock()
        m.select.return_value = m
        m.eq.return_value = m
        m.order.return_value = m
        m.limit.return_value = m
        m.update.return_value = m
        m.insert.return_value = m
        m.execute.return_value = canned.get(name, Mock(data=[]))
        return m
    return _table


class TestGetRecentOrders:
    @pytest.mark.asyncio
    async def test_returns_orders_for_customer(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "orders": Mock(data=[{"id": "order-1", "status": "processing", "total": 20.0}]),
        }))
        service = PostSaleService(db=db)

        orders = await service.get_recent_orders("tenant-1", "+123", limit=3)

        assert len(orders) == 1
        assert orders[0]["id"] == "order-1"

    def test_format_order_status_message_known_status(self):
        service = PostSaleService(db=MagicMock())
        message = service.format_order_status_message({"id": "order-12345678", "status": "ready", "total": 15.5})
        assert "12345678"[-8:] in message
        assert "listo" in message.lower()

    def test_format_order_status_message_unknown_status_falls_back(self):
        service = PostSaleService(db=MagicMock())
        message = service.format_order_status_message({"id": "order-1", "status": "some_new_status", "total": 10})
        assert "some_new_status" in message


class TestCreateRequest:
    @pytest.mark.asyncio
    async def test_creates_request_and_notifies_seller(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "post_sale_requests": Mock(data=[{"id": "req-1", "status": "open"}]),
            "whatsapp_configs": Mock(data=[{
                "seller_phone": "+5550001111", "phone_number": "+5550001111",
                "phone_number_id": "phone-id", "access_token": encrypt_token("token"),
            }]),
        }))
        service = PostSaleService(db=db)

        with patch("services.post_sale_service.MetaWhatsAppService") as mock_meta:
            request = await service.create_request("tenant-1", "+123", "order-1", "return", "Llegó dañado")

        assert request == {"id": "req-1", "status": "open"}
        mock_meta.return_value.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_seller_configured_does_not_raise(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "post_sale_requests": Mock(data=[{"id": "req-1"}]),
            "whatsapp_configs": Mock(data=[]),
        }))
        service = PostSaleService(db=db)

        request = await service.create_request("tenant-1", "+123", None, "question", "¿Cuándo llega?")

        assert request == {"id": "req-1"}

    @pytest.mark.asyncio
    async def test_insert_failure_returns_none(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "post_sale_requests": Mock(data=[]),
        }))
        service = PostSaleService(db=db)

        request = await service.create_request("tenant-1", "+123", None, "question", "hola")

        assert request is None


class TestResolveRequest:
    @pytest.mark.asyncio
    async def test_resolve_updates_status_and_requests_rating(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "post_sale_requests": Mock(data=[{"id": "req-1", "customer_phone": "+123", "status": "resolved"}]),
            "whatsapp_configs": Mock(data=[{"phone_number_id": "phone-id", "access_token": encrypt_token("token")}]),
            "conversation_sessions": Mock(data=[{"id": "session-1", "session_data": {"cart": []}}]),
        }))
        service = PostSaleService(db=db)

        with patch("services.post_sale_service.MetaWhatsAppService") as mock_meta:
            resolved = await service.resolve_request("tenant-1", "req-1")

        assert resolved is True
        mock_meta.return_value.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolve_nonexistent_request_returns_false(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "post_sale_requests": Mock(data=[]),
        }))
        service = PostSaleService(db=db)

        resolved = await service.resolve_request("tenant-1", "missing-id")

        assert resolved is False


class TestRateSatisfaction:
    @pytest.mark.asyncio
    async def test_rate_satisfaction_updates_row(self):
        db = MagicMock()
        db.table = Mock(side_effect=make_table_router({
            "post_sale_requests": Mock(data=[{"id": "req-1", "satisfaction_rating": 5}]),
        }))
        service = PostSaleService(db=db)

        result = await service.rate_satisfaction("req-1", 5)

        assert result is True
