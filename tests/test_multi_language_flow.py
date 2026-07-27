"""
Integration tests for multi-language conversation handling
(spec requirement 15) through MetaWhatsAppBotService.process_message.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from services.i18n import t


def make_service(session_data=None, default_language="es"):
    with patch("services.whatsapp.meta_bot_service.get_supabase_client", return_value=MagicMock()):
        from services.whatsapp.meta_bot_service import MetaWhatsAppBotService
        service = MetaWhatsAppBotService()

    service._get_tenant = AsyncMock(return_value={
        "id": "tenant-1", "name": "Mi Tienda", "onboarding_status": "completed",
    })
    service._get_tenant_config = AsyncMock(return_value={})
    service._get_or_create_session = AsyncMock(return_value={
        "id": "session-1", "session_data": session_data or {},
    })
    # Default: no stored session row, so the translation notice hasn't been
    # sent yet. Without this the bare MagicMock returns truthy for every
    # .get(), which reads as "already notified".
    service.db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = Mock(
        data=[]
    )

    service._log_message = AsyncMock()
    service._is_seller = AsyncMock(return_value=False)
    service.offline_service.is_offline = AsyncMock(return_value=False)
    service._get_tenant_default_language = AsyncMock(return_value=default_language)
    service._persist_session_language = AsyncMock()
    service.llm_handler.can_handle = AsyncMock(return_value=False)
    service.onboarding_chain.process = AsyncMock(return_value=None)
    return service


def capture_language(service):
    """Make the fallback chain record the language it was handed."""
    seen = {}

    async def _process(message_data):
        seen["language"] = message_data.get("language")
        return "handled"

    service.fallback_chain.process = AsyncMock(side_effect=_process)
    return seen


class TestLanguageDetection:
    @pytest.mark.asyncio
    async def test_english_customer_gets_english_language(self):
        service = make_service()
        seen = capture_language(service)

        with patch("services.whatsapp.meta_bot_service.tenant_has_feature", AsyncMock(return_value=True)):
            await service.process_message("tenant-1", "+1", "hello, I want a burger", "phone-id")

        assert seen["language"] == "en"

    @pytest.mark.asyncio
    async def test_portuguese_customer_gets_portuguese_language(self):
        service = make_service()
        seen = capture_language(service)

        with patch("services.whatsapp.meta_bot_service.tenant_has_feature", AsyncMock(return_value=True)):
            await service.process_message("tenant-1", "+1", "bom dia, quanto custa?", "phone-id")

        assert seen["language"] == "pt"

    @pytest.mark.asyncio
    async def test_language_switch_mid_conversation(self):
        """Requirement 15.4: a confident detection overrides the sticky
        language the conversation had been using."""
        service = make_service(session_data={"language": "es"})
        seen = capture_language(service)

        with patch("services.whatsapp.meta_bot_service.tenant_has_feature", AsyncMock(return_value=True)):
            await service.process_message("tenant-1", "+1", "hello, I changed my mind", "phone-id")

        assert seen["language"] == "en"

    @pytest.mark.asyncio
    async def test_ambiguous_message_keeps_sticky_language(self):
        """A bare "ok" carries no signal and must not reset an English
        conversation back to Spanish."""
        service = make_service(session_data={"language": "en"})
        seen = capture_language(service)

        with patch("services.whatsapp.meta_bot_service.tenant_has_feature", AsyncMock(return_value=True)):
            await service.process_message("tenant-1", "+1", "1", "phone-id")

        assert seen["language"] == "en"

    @pytest.mark.asyncio
    async def test_no_signal_and_no_history_uses_tenant_default(self):
        service = make_service(default_language="pt")
        seen = capture_language(service)

        with patch("services.whatsapp.meta_bot_service.tenant_has_feature", AsyncMock(return_value=True)):
            await service.process_message("tenant-1", "+1", "1", "phone-id")

        assert seen["language"] == "pt"

    @pytest.mark.asyncio
    async def test_detected_language_is_persisted(self):
        service = make_service()
        capture_language(service)

        with patch("services.whatsapp.meta_bot_service.tenant_has_feature", AsyncMock(return_value=True)):
            await service.process_message("tenant-1", "+1", "hello there", "phone-id")

        service._persist_session_language.assert_awaited_once_with("session-1", "en")


class TestTierGating:
    @pytest.mark.asyncio
    async def test_free_tenant_always_spanish(self):
        """Degrades silently - a customer should never see an upsell nag."""
        service = make_service()
        seen = capture_language(service)

        with patch("services.whatsapp.meta_bot_service.tenant_has_feature", AsyncMock(return_value=False)):
            response = await service.process_message(
                "tenant-1", "+1", "hello, I want a burger", "phone-id"
            )

        assert seen["language"] == "es"
        assert "premium" not in (response or "").lower()

    @pytest.mark.asyncio
    async def test_seller_always_spanish(self):
        service = make_service()
        service._is_seller = AsyncMock(return_value=True)
        service.offline_service.record_seller_activity = AsyncMock()
        service.offline_service.notify_seller_of_pending_messages = AsyncMock()

        seen = {}

        async def _seller_process(message_data):
            seen["language"] = message_data.get("language")
            return "resumen"

        service.seller_chain.process = AsyncMock(side_effect=_seller_process)

        with patch("services.whatsapp.meta_bot_service.tenant_has_feature", AsyncMock(return_value=True)):
            await service.process_message("tenant-1", "+5550001111", "hello", "phone-id")

        assert seen["language"] == "es"


class TestTranslationNotice:
    @pytest.mark.asyncio
    async def test_notice_appended_when_language_differs_from_tenant(self):
        """Requirement 15.3: product names stay in the seller's language,
        so the customer is told the rest is machine-translated."""
        service = make_service(default_language="es")
        service.fallback_chain.process = AsyncMock(return_value="Here is our menu")

        with patch("services.whatsapp.meta_bot_service.tenant_has_feature", AsyncMock(return_value=True)):
            response = await service.process_message("tenant-1", "+1", "hello there", "phone-id")

        assert t("translation.notice", "en") in response

    @pytest.mark.asyncio
    async def test_no_notice_when_language_matches_tenant(self):
        service = make_service(default_language="es")
        service.fallback_chain.process = AsyncMock(return_value="Aquí está el menú")

        with patch("services.whatsapp.meta_bot_service.tenant_has_feature", AsyncMock(return_value=True)):
            response = await service.process_message(
                "tenant-1", "+1", "hola quiero el menu", "phone-id"
            )

        assert response == "Aquí está el menú"

    @pytest.mark.asyncio
    async def test_notice_sent_only_once_per_conversation(self):
        service = make_service(default_language="es")
        service.fallback_chain.process = AsyncMock(return_value="Here is our menu")
        service.db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = Mock(
            data=[{"session_data": {"translation_notice_sent": True}}]
        )

        with patch("services.whatsapp.meta_bot_service.tenant_has_feature", AsyncMock(return_value=True)):
            response = await service.process_message("tenant-1", "+1", "hello there", "phone-id")

        assert response == "Here is our menu"


class TestLocalizedResponses:
    @pytest.mark.asyncio
    async def test_default_response_is_localized(self):
        service = make_service()
        service.fallback_chain.process = AsyncMock(return_value=None)

        with patch("services.whatsapp.meta_bot_service.tenant_has_feature", AsyncMock(return_value=True)):
            response = await service.process_message("tenant-1", "+1", "hello there", "phone-id")

        assert t("bot.default_menu", "en").split("\n")[0] in response

    @pytest.mark.asyncio
    async def test_offline_reply_uses_customer_language(self):
        service = make_service()
        service.offline_service.is_offline = AsyncMock(return_value=True)
        service.offline_service.get_offline_reply = AsyncMock(
            side_effect=lambda tenant_id, language: t("offline.default_reply", language)
        )
        service.offline_service.store_offline_message = AsyncMock()

        with patch("services.whatsapp.meta_bot_service.tenant_has_feature", AsyncMock(return_value=True)):
            response = await service.process_message("tenant-1", "+1", "hello, are you open?", "phone-id")

        assert response == t("offline.default_reply", "en")
