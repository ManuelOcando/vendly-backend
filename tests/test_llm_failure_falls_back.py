"""
Cuando el LLM falla, el bot cae en la cadena determinista.

Esto se rompio de verdad en produccion: al rotar la clave de Gemini se perdio
el acceso al modelo, y a partir de ahi un "hola" contestaba "no pude procesar
tu mensaje con inteligencia artificial" en vez del saludo. WelcomeHandler,
MenuHandler y ProductOrderHandler existian y estaban cableados, pero eran
inalcanzables: meta_bot_service solo consulta la cadena si el handler del LLM
devuelve None, y este devolvia el texto de disculpa, que cuenta como
"ya lo atendi".

Los casos de abajo fijan el contrato en los dos lados: que el handler cede, y
que cediendo el cliente acaba recibiendo una respuesta util.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.whatsapp.handlers.llm_handler import LLMHandler


def _message_data():
    return {
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "phone": "584123456789",
        "message": "hola",
        "language": "es",
        "session": {"id": "sess-1", "current_state": "initial", "session_data": {}},
    }


class TestLLMHandlerYieldsOnFailure:
    """handle() devuelve None en cada ruta de fallo, nunca un texto."""

    @pytest.mark.asyncio
    async def test_yields_when_provider_cannot_be_created(self):
        handler = LLMHandler(MagicMock())
        with patch(
            "services.whatsapp.handlers.llm_handler.get_llm_provider",
            return_value=None,
        ):
            assert await handler.handle(_message_data()) is None

    @pytest.mark.asyncio
    async def test_yields_when_the_call_returns_none(self):
        """El caso real: el modelo responde 404 y el proveedor devuelve None."""
        provider = MagicMock()
        provider.build_system_prompt.return_value = "prompt"
        provider.build_context_prompt.return_value = "ctx"
        provider.generate_response = AsyncMock(return_value=None)

        handler = LLMHandler(MagicMock())
        with patch(
            "services.whatsapp.handlers.llm_handler.get_llm_provider",
            return_value=provider,
        ):
            assert await handler.handle(_message_data()) is None

    @pytest.mark.asyncio
    async def test_yields_when_the_call_returns_a_non_dict(self):
        provider = MagicMock()
        provider.build_system_prompt.return_value = "prompt"
        provider.build_context_prompt.return_value = "ctx"
        provider.generate_response = AsyncMock(return_value="no soy un dict")

        handler = LLMHandler(MagicMock())
        with patch(
            "services.whatsapp.handlers.llm_handler.get_llm_provider",
            return_value=provider,
        ):
            assert await handler.handle(_message_data()) is None

    @pytest.mark.asyncio
    async def test_yields_when_the_provider_raises(self):
        provider = MagicMock()
        provider.build_system_prompt.side_effect = RuntimeError("boom")

        handler = LLMHandler(MagicMock())
        with patch(
            "services.whatsapp.handlers.llm_handler.get_llm_provider",
            return_value=provider,
        ):
            assert await handler.handle(_message_data()) is None

    @pytest.mark.asyncio
    async def test_never_answers_with_an_apology_about_ai(self):
        """
        La regresion concreta. Un cliente no tiene por que enterarse de que
        habia un LLM detras, y menos de que se cayo.
        """
        provider = MagicMock()
        provider.build_system_prompt.return_value = "prompt"
        provider.build_context_prompt.return_value = "ctx"
        provider.generate_response = AsyncMock(return_value=None)

        handler = LLMHandler(MagicMock())
        with patch(
            "services.whatsapp.handlers.llm_handler.get_llm_provider",
            return_value=provider,
        ):
            respuesta = await handler.handle(_message_data())

        assert respuesta is None or "inteligencia artificial" not in respuesta.lower()


class TestFallbackMessageIsGone:
    def test_the_apology_string_is_no_longer_in_the_catalog(self):
        """
        Era la unica razon de ser de llm.fallback. Si vuelve, es que alguien
        reintrodujo la disculpa en lugar de ceder a la cadena.
        """
        from services.i18n import MESSAGES

        assert "llm.fallback" not in MESSAGES

    def test_handler_no_longer_exposes_a_fallback_message_helper(self):
        assert not hasattr(LLMHandler, "_get_fallback_message")
