"""
Integration test for the intelligent offline mode short-circuit in
MetaWhatsAppBotService.process_message (spec requirement 14).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def make_service():
    with patch("services.whatsapp.meta_bot_service.get_supabase_client", return_value=MagicMock()):
        from services.whatsapp.meta_bot_service import MetaWhatsAppBotService
        service = MetaWhatsAppBotService()

    service._get_tenant = AsyncMock(return_value={"id": "tenant-1", "name": "Mi Tienda", "onboarding_status": "completed"})
    service._get_tenant_config = AsyncMock(return_value={})
    service._get_or_create_session = AsyncMock(return_value={"id": "session-1"})
    service._log_message = AsyncMock()
    return service


class TestOfflineShortCircuit:
    @pytest.mark.asyncio
    async def test_customer_message_while_offline_skips_normal_handlers(self):
        service = make_service()
        service._is_seller = AsyncMock(return_value=False)
        service.offline_service.is_offline = AsyncMock(return_value=True)
        service.offline_service.get_offline_reply = AsyncMock(return_value="Estamos fuera de horario")
        service.offline_service.store_offline_message = AsyncMock()
        service.llm_handler.can_handle = AsyncMock(side_effect=AssertionError("should not reach LLM handler"))
        service.fallback_chain.process = AsyncMock(side_effect=AssertionError("should not reach fallback chain"))
        service.onboarding_chain.process = AsyncMock(side_effect=AssertionError("should not reach onboarding"))

        response = await service.process_message("tenant-1", "+1234567890", "hola, siguen abiertos?", "phone-id")

        assert response == "Estamos fuera de horario"
        service.offline_service.store_offline_message.assert_called_once_with(
            "tenant-1", "+1234567890", "hola, siguen abiertos?"
        )

    @pytest.mark.asyncio
    async def test_customer_message_while_online_reaches_normal_handlers(self):
        service = make_service()
        service._is_seller = AsyncMock(return_value=False)
        service.offline_service.is_offline = AsyncMock(return_value=False)
        service.offline_service.store_offline_message = AsyncMock()
        service.llm_handler.can_handle = AsyncMock(return_value=False)
        service.fallback_chain.process = AsyncMock(return_value="Claro, tenemos varios productos.")

        response = await service.process_message("tenant-1", "+1234567890", "que productos tienen?", "phone-id")

        assert response == "Claro, tenemos varios productos."
        service.offline_service.store_offline_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_onboarding_tenant_bypasses_offline_check(self):
        """A tenant still mid-onboarding must never be told the bot is
        offline, even if it already has restrictive hours configured -
        the person messaging during onboarding is the seller setting up
        shop, not a real customer."""
        service = make_service()
        service._get_tenant = AsyncMock(return_value={"id": "tenant-1", "name": "Mi Tienda", "onboarding_status": "in_progress"})
        service._is_seller = AsyncMock(return_value=False)
        service.offline_service.is_offline = AsyncMock(return_value=True)
        service.llm_handler.can_handle = AsyncMock(return_value=False)
        service.fallback_chain.process = AsyncMock(return_value=None)
        service.onboarding_chain.process = AsyncMock(return_value="Bienvenido, continuemos con tu configuración.")

        response = await service.process_message("tenant-1", "+1234567890", "Lunes a Viernes: 9:00 - 21:00", "phone-id")

        assert response == "Bienvenido, continuemos con tu configuración."
        service.offline_service.is_offline.assert_not_called()

    @pytest.mark.asyncio
    async def test_seller_message_records_activity_and_flushes_pending(self):
        service = make_service()
        service._is_seller = AsyncMock(return_value=True)
        service.offline_service.record_seller_activity = AsyncMock()
        service.offline_service.notify_seller_of_pending_messages = AsyncMock()
        service.seller_chain.process = AsyncMock(return_value="Resumen del día...")

        response = await service.process_message("tenant-1", "+5550001111", "resumen", "phone-id")

        assert response == "Resumen del día..."
        service.offline_service.record_seller_activity.assert_called_once_with("tenant-1")
