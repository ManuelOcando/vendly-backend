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
    async def test_yields_when_the_provider_returns_its_own_filler(self):
        """
        Cuando el proveedor no puede parsear su salida devuelve un dict con
        forma valida y llm_error=True. Sin mirar la bandera se cuela como
        respuesta buena y el cliente recibe "Disculpa, hubo un error" en vez
        del saludo o el catalogo que la cadena si sabe dar.
        """
        provider = MagicMock()
        provider.build_system_prompt.return_value = "prompt"
        provider.build_context_prompt.return_value = "ctx"
        provider.generate_response = AsyncMock(
            return_value={
                "llm_error": True,
                "intention": "other",
                "response_text": "Disculpa, hubo un error. ¿Puedes repetir tu pedido?",
                "products": [],
                "questions": [],
            }
        )

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


class TestElEstadoMandaSobreElLLM:
    """
    Un "si" que responde a una pregunta del bot va al handler determinista,
    aunque el LLM este disponible.

    Esto fallo en la primera conversacion real. LLMHandler.can_handle decide
    mirando solo el texto y nunca el estado, asi que el "si" con el que el
    cliente confirmaba su pedido acababa en el modelo, que lo recibia suelto y
    sin anclaje: invento un pedido de 17 hamburguesas con modificadores que se
    contradecian ("con queso, sin queso"), piso los productos que el cliente si
    habia pedido, y el siguiente "si" respondio "tu carrito esta vacio".
    """

    def _bot(self):
        from services.whatsapp.meta_bot_service import MetaWhatsAppBotService

        with patch("services.whatsapp.meta_bot_service.get_supabase_client", MagicMock()):
            return MetaWhatsAppBotService()

    @pytest.mark.asyncio
    async def test_un_si_esperando_confirmacion_no_llega_al_llm(self):
        bot = self._bot()
        datos = _message_data()
        datos["message"] = "si"
        datos["session"]["session_data"] = {
            "awaiting_confirmation": True,
            "pending_products": [{"product_id": "p-1", "name": "Hamburguesa",
                                  "price": 10.0, "quantity": 1}],
        }

        assert await bot._la_conversacion_espera_una_respuesta(datos) is True

    @pytest.mark.asyncio
    async def test_un_si_con_el_carrito_listo_tampoco(self):
        bot = self._bot()
        datos = _message_data()
        datos["message"] = "si"
        datos["session"]["current_state"] = "ordering"
        datos["session"]["session_data"] = {
            "cart": [{"product_id": "p-1", "name": "Hamburguesa", "price": 10.0, "quantity": 1}]
        }

        assert await bot._la_conversacion_espera_una_respuesta(datos) is True

    @pytest.mark.asyncio
    async def test_un_mensaje_normal_si_llega_al_llm(self):
        """El desvio es estrecho: solo cuando hay algo que confirmar."""
        bot = self._bot()
        datos = _message_data()
        datos["message"] = "quiero una hamburguesa"

        assert await bot._la_conversacion_espera_una_respuesta(datos) is False

    @pytest.mark.asyncio
    async def test_un_si_sin_nada_pendiente_llega_al_llm(self):
        bot = self._bot()
        datos = _message_data()
        datos["message"] = "si"

        assert await bot._la_conversacion_espera_una_respuesta(datos) is False
