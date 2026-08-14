"""
Que se vea cuando el bot esta contestando sin LLM.

La noche del 13/08/2026 el bot dejo de entender modificaciones, dejo de
entender "eso es todo" y dejo de saber cancelar. Parecia una regresion del
ultimo despliegue y se fueron veinte minutos buscandola en el codigo.

No era eso. Se habia agotado la cuota diaria del plan gratuito de Gemini --
veinte peticiones al dia -- y LLMHandler.handle hacia lo correcto: ceder a la
cadena determinista. Ceder es correcto; hacerlo en silencio no. El unico rastro
era un CRITICAL ERROR en los logs de Render, y lo que veia el comerciante era un
bot mas tonto sin explicacion.

Esto no arregla la cuota. La hace visible.
"""
import pytest

from services.llm import salud


@pytest.fixture(autouse=True)
def _limpio():
    salud.reiniciar()
    yield
    salud.reiniciar()


class TestReconocerLaCuota:
    @pytest.mark.parametrize("mensaje", [
        "429 RESOURCE_EXHAUSTED",
        "You exceeded your current quota, please check your plan",
        "quota_id: GenerateRequestsPerDayPerProjectPerModel-FreeTier",
        "Rate limit reached for gpt-4",
        "Too Many Requests",
    ])
    def test_los_mensajes_de_los_proveedores(self, mensaje):
        """
        Se busca en el texto porque cada proveedor lanza su propia excepcion y
        no hay un tipo comun que capturar.
        """
        salud.registrar_fallo(RuntimeError(mensaje))
        assert salud.informe()["causa"] == "cuota_agotada"

    def test_un_fallo_normal_no_se_confunde_con_cuota(self):
        salud.registrar_fallo(ConnectionError("connection reset by peer"))
        assert salud.informe()["causa"] == "error"

    def test_la_cuota_dice_que_hacer(self):
        """Quien lo lea a las once de la noche no deberia tener que investigar."""
        salud.registrar_fallo(RuntimeError("429 quota exceeded"))
        assert "20 peticiones al dia" in salud.informe()["que_hacer"]


class TestElInforme:
    def test_sin_fallos_no_esta_degradado(self):
        assert salud.informe()["degradado"] is False

    def test_un_fallo_lo_marca_degradado(self):
        salud.registrar_fallo(RuntimeError("boom"))
        assert salud.informe()["degradado"] is True

    def test_un_exito_posterior_lo_limpia(self):
        """Un fallo de hace horas no describe el presente."""
        salud.registrar_fallo(RuntimeError("boom"))
        salud.registrar_exito()

        informe = salud.informe()
        assert informe["degradado"] is False
        assert informe["fallos_seguidos"] == 0
        assert "motivo" not in informe

    def test_cuenta_los_fallos_seguidos(self):
        """Uno puede ser un mal minuto; veinte seguidos es otra cosa."""
        for _ in range(3):
            salud.registrar_fallo(RuntimeError("boom"))
        assert salud.informe()["fallos_seguidos"] == 3

    def test_el_motivo_no_ocupa_media_pantalla(self):
        """Los errores de cuota de Google traen media pagina de facturacion."""
        salud.registrar_fallo(RuntimeError("x" * 5000))
        assert len(salud.informe()["motivo"]) <= 320


class TestSaleEnHealth:
    def test_el_endpoint_lo_incluye(self):
        from fastapi.testclient import TestClient

        import main

        salud.registrar_fallo(RuntimeError("429 quota exceeded"))
        cuerpo = TestClient(main.app).get("/api/v1/health").json()

        assert cuerpo["llm"]["degradado"] is True
        assert cuerpo["llm"]["causa"] == "cuota_agotada"

    def test_sano_no_alarma(self):
        from fastapi.testclient import TestClient

        import main

        salud.registrar_exito()
        cuerpo = TestClient(main.app).get("/api/v1/health").json()

        assert cuerpo["llm"]["degradado"] is False


class TestElHandlerLoRegistra:
    @pytest.mark.asyncio
    async def test_una_excepcion_del_proveedor_queda_apuntada(self):
        from unittest.mock import MagicMock, patch

        from services.whatsapp.handlers.llm_handler import LLMHandler

        handler = LLMHandler(MagicMock())
        datos = {
            "tenant_id": "t-1", "phone": "+1", "message": "hola", "language": "es",
            "session": {"id": "s-1", "current_state": "initial", "session_data": {}},
        }

        with patch(
            "services.whatsapp.handlers.llm_handler.get_llm_provider",
            side_effect=RuntimeError("429 RESOURCE_EXHAUSTED quota"),
        ):
            assert await handler.handle(datos) is None      # cede, como debe

        informe = salud.informe()
        assert informe["degradado"] is True
        assert informe["causa"] == "cuota_agotada"
