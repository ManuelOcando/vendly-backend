"""
Tests for PostSaleHandler, ServiceSchedulingHandler, and the
LLMHandler deterministic-intent routing fix.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock, Mock

from services.whatsapp.handlers.post_sale import PostSaleHandler
from services.whatsapp.handlers.scheduling import ServiceSchedulingHandler
from services.whatsapp.handlers.llm_handler import LLMHandler, _is_deterministic_intent


def make_message_data(message, session=None, **overrides):
    data = {
        "tenant_id": "tenant-1",
        "phone": "+1234567890",
        "message": message,
        "session": session if session is not None else {
            "id": "session-1", "current_state": "initial", "session_data": {},
        },
    }
    data.update(overrides)
    return data


class TestLLMHandlerDeterministicRouting:
    @pytest.mark.parametrize("message", [
        "pedido:cart-123",
        "¿cuál es el estado de mi pedido?",
        "donde esta mi pedido",
        "quiero un reembolso",
        "quiero devolver esto",
        "quiero agendar una cita",
        "quiero reservar",
        "cancelar mi cita",
    ])
    def test_deterministic_intents_detected(self, message):
        assert _is_deterministic_intent(message) is True

    @pytest.mark.parametrize("message", [
        "hola",
        "quiero una hamburguesa",
        "agregar a mi pedido",
        "cuánto cuesta",
    ])
    def test_non_deterministic_messages_not_flagged(self, message):
        assert _is_deterministic_intent(message) is False

    @pytest.mark.asyncio
    async def test_can_handle_returns_false_for_deterministic_intent(self):
        handler = LLMHandler(MagicMock())
        result = await handler.can_handle(make_message_data("estado de mi pedido"))
        assert result is False

    @pytest.mark.asyncio
    async def test_can_handle_returns_true_for_normal_message_when_llm_enabled(self):
        handler = LLMHandler(MagicMock())
        with patch("services.whatsapp.handlers.llm_handler.get_settings") as mock_settings:
            mock_settings.return_value = Mock(
                LLM_ENABLED=True, LLM_PROVIDER="gemini", GEMINI_API_KEY="key",
            )
            result = await handler.can_handle(make_message_data("hola, quiero una hamburguesa"))
        assert result is True


class TestPostSaleHandlerCanHandle:
    @pytest.mark.asyncio
    async def test_matches_order_status_keyword(self):
        handler = PostSaleHandler(MagicMock())
        result = await handler.can_handle(make_message_data("¿cuál es el estado de mi pedido?"))
        assert result is True

    @pytest.mark.asyncio
    async def test_matches_return_keyword(self):
        handler = PostSaleHandler(MagicMock())
        result = await handler.can_handle(make_message_data("quiero un reembolso"))
        assert result is True

    @pytest.mark.asyncio
    async def test_defers_to_cart_flow_during_checkout(self):
        handler = PostSaleHandler(MagicMock())
        session = {"id": "session-1", "current_state": "viewing_cart", "session_data": {}}
        result = await handler.can_handle(make_message_data("devolver", session=session))
        assert result is False

    @pytest.mark.asyncio
    async def test_still_handles_requests_after_an_order_was_placed(self):
        """`payment_pending` is set when the order is created and never
        cleared, so treating it as "checkout in progress" locked customers
        out of post-sale support for good after their first purchase."""
        handler = PostSaleHandler(MagicMock())
        session = {"id": "session-1", "current_state": "payment_pending", "session_data": {}}
        result = await handler.can_handle(make_message_data("devolver", session=session))
        assert result is True

    @pytest.mark.asyncio
    async def test_pending_satisfaction_rating_takes_priority(self):
        handler = PostSaleHandler(MagicMock())
        session = {
            "id": "session-1", "current_state": "initial",
            "session_data": {"awaiting_satisfaction_for": "req-1"},
        }
        result = await handler.can_handle(make_message_data("5", session=session))
        assert result is True

    @pytest.mark.asyncio
    async def test_unrelated_message_not_handled(self):
        handler = PostSaleHandler(MagicMock())
        result = await handler.can_handle(make_message_data("hola"))
        assert result is False


class TestPostSaleHandlerHandle:
    @pytest.mark.asyncio
    async def test_status_inquiry_returns_formatted_orders(self):
        handler = PostSaleHandler(MagicMock())
        with patch("services.whatsapp.handlers.post_sale.PostSaleService") as mock_service_cls:
            mock_service_cls.return_value.get_recent_orders = AsyncMock(
                return_value=[{"id": "order-1", "status": "processing", "total": 10.0}]
            )
            mock_service_cls.return_value.format_order_status_message = Mock(
                return_value="Pedido #order-1 - $10.00\nTu pedido está en preparación."
            )
            response = await handler.handle(make_message_data("estado de mi pedido"))

        assert "preparación" in response

    @pytest.mark.asyncio
    async def test_status_inquiry_no_orders_found(self):
        handler = PostSaleHandler(MagicMock())
        with patch("services.whatsapp.handlers.post_sale.PostSaleService") as mock_service_cls:
            mock_service_cls.return_value.get_recent_orders = AsyncMock(return_value=[])
            response = await handler.handle(make_message_data("estado de mi pedido"))

        assert "No encontré pedidos" in response

    @pytest.mark.asyncio
    async def test_return_request_creates_and_confirms(self):
        handler = PostSaleHandler(MagicMock())
        with patch("services.whatsapp.handlers.post_sale.PostSaleService") as mock_service_cls:
            mock_service_cls.return_value.get_recent_orders = AsyncMock(
                return_value=[{"id": "order-1"}]
            )
            mock_service_cls.return_value.create_request = AsyncMock(return_value={"id": "req-1"})
            response = await handler.handle(make_message_data("quiero devolver el producto"))

        assert "Recibimos tu solicitud" in response
        mock_service_cls.return_value.create_request.assert_awaited_once_with(
            "tenant-1", "+1234567890", "order-1", "return", "quiero devolver el producto"
        )

    @pytest.mark.asyncio
    async def test_satisfaction_rating_captured_and_session_cleared(self):
        handler = PostSaleHandler(MagicMock())
        session = {
            "id": "session-1", "current_state": "initial",
            "session_data": {"awaiting_satisfaction_for": "req-1"},
        }
        handler.update_session_state = AsyncMock()

        with patch("services.whatsapp.handlers.post_sale.PostSaleService") as mock_service_cls:
            mock_service_cls.return_value.rate_satisfaction = AsyncMock(return_value=True)
            response = await handler.handle(make_message_data("5", session=session))

        assert "Gracias por tu calificación" in response
        mock_service_cls.return_value.rate_satisfaction.assert_awaited_once_with("req-1", 5)
        handler.update_session_state.assert_awaited_once()
        saved_session_data = handler.update_session_state.call_args.args[2]
        assert "awaiting_satisfaction_for" not in saved_session_data

    @pytest.mark.asyncio
    async def test_satisfaction_rating_out_of_range_rejected(self):
        handler = PostSaleHandler(MagicMock())
        session = {
            "id": "session-1", "current_state": "initial",
            "session_data": {"awaiting_satisfaction_for": "req-1"},
        }
        with patch("services.whatsapp.handlers.post_sale.PostSaleService"):
            response = await handler.handle(make_message_data("9", session=session))

        assert "1 al 5" in response


class TestServiceSchedulingHandlerCanHandle:
    @pytest.mark.asyncio
    async def test_matches_booking_keyword(self):
        handler = ServiceSchedulingHandler(MagicMock())
        result = await handler.can_handle(make_message_data("quiero agendar una cita"))
        assert result is True

    @pytest.mark.asyncio
    async def test_matches_mid_flow_state(self):
        handler = ServiceSchedulingHandler(MagicMock())
        session = {"id": "session-1", "current_state": "scheduling_service", "session_data": {}}
        result = await handler.can_handle(make_message_data("1", session=session))
        assert result is True

    @pytest.mark.asyncio
    async def test_unrelated_message_not_handled(self):
        handler = ServiceSchedulingHandler(MagicMock())
        result = await handler.can_handle(make_message_data("hola"))
        assert result is False


class TestServiceSchedulingHandlerFlow:
    @pytest.mark.asyncio
    async def test_start_booking_lists_services(self):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = Mock(
            data=[{"id": "svc-1", "name": "Corte de cabello"}]
        )
        handler = ServiceSchedulingHandler(db)
        handler.update_session_state = AsyncMock()

        response = await handler.handle(make_message_data("quiero agendar una cita"))

        assert "Corte de cabello" in response
        handler.update_session_state.assert_awaited_once()
        state_arg = handler.update_session_state.call_args.args[1]
        assert state_arg == "scheduling_service"

    @pytest.mark.asyncio
    async def test_select_service_advances_to_date_step(self):
        handler = ServiceSchedulingHandler(MagicMock())
        handler.update_session_state = AsyncMock()
        session = {
            "id": "session-1", "current_state": "scheduling_service",
            "session_data": {"scheduling": {
                "step": "selecting_service",
                "services": [{"id": "svc-1", "name": "Corte de cabello"}],
            }},
        }

        response = await handler.handle(make_message_data("1", session=session))

        assert "Elegiste: Corte de cabello" in response
        saved_data = handler.update_session_state.call_args.args[2]
        assert saved_data["scheduling"]["step"] == "selecting_date"
        assert saved_data["scheduling"]["item_id"] == "svc-1"

    @pytest.mark.asyncio
    async def test_select_service_invalid_choice_reprompts(self):
        handler = ServiceSchedulingHandler(MagicMock())
        session = {
            "id": "session-1", "current_state": "scheduling_service",
            "session_data": {"scheduling": {
                "step": "selecting_service",
                "services": [{"id": "svc-1", "name": "Corte de cabello"}],
            }},
        }

        response = await handler.handle(make_message_data("no entiendo", session=session))

        assert "número del servicio" in response

    @pytest.mark.asyncio
    async def test_confirm_booking_creates_appointment(self):
        from datetime import datetime
        handler = ServiceSchedulingHandler(MagicMock())
        handler.update_session_state = AsyncMock()
        selected_slot = datetime(2026, 8, 1, 10, 0).isoformat()
        session = {
            "id": "session-1", "current_state": "scheduling_service",
            "session_data": {"scheduling": {
                "step": "confirming", "item_id": "svc-1", "item_name": "Corte de cabello",
                "selected_slot": selected_slot,
            }},
        }

        with patch("services.whatsapp.handlers.scheduling.SchedulingService") as mock_service_cls:
            mock_service_cls.return_value.create_appointment = AsyncMock(
                return_value={"id": "appt-1"}
            )
            response = await handler.handle(make_message_data("sí", session=session))

        assert "Cita confirmada" in response
        mock_service_cls.return_value.create_appointment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_confirm_booking_declines_on_no(self):
        handler = ServiceSchedulingHandler(MagicMock())
        handler.update_session_state = AsyncMock()
        session = {
            "id": "session-1", "current_state": "scheduling_service",
            "session_data": {"scheduling": {
                "step": "confirming", "item_id": "svc-1", "item_name": "Corte de cabello",
                "selected_slot": "2026-08-01T10:00:00",
            }},
        }

        response = await handler.handle(make_message_data("no", session=session))

        assert "Cita cancelada" in response

    @pytest.mark.asyncio
    async def test_cancel_appointment_keyword_routes_to_cancellation(self):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = Mock(
            data=[{"id": "appt-1"}]
        )
        handler = ServiceSchedulingHandler(db)

        with patch("services.whatsapp.handlers.scheduling.SchedulingService") as mock_service_cls:
            mock_service_cls.return_value.cancel_appointment = AsyncMock(
                return_value={"success": True, "message_key": "scheduling.cancel_success"}
            )
            response = await handler.handle(make_message_data("cancelar mi cita"))

        assert response == "Tu cita fue cancelada."
