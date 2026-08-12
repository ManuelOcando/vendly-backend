"""
La politica de CORS: a quien se le permite leer nuestras respuestas.

CORS lo aplica el navegador, no el servidor. Un comodin aqui no abre la API a
curl -- curl nunca la miro -- sino que deja que el JavaScript de cualquier web
lea respuestas de Vendly en el navegador del usuario. Peor: con credenciales
activas Starlette refleja el origen de quien llama, asi que "*" tampoco es el
comodin anonimo que aparenta.

main.py traia dos ramas que lo añadian. La de produccion pedia len(origins) < 2
y nunca se cumplia, porque la lista trae tres literales fijos: codigo muerto
aparentando proteccion. La de DEBUG si se cumplia, y bastaba con poner
DEBUG=true en Render para abrir la API entera sin que nada avisara.

El ultimo test de este archivo es el que impide que esa rama vuelva.
"""
import importlib

import pytest
from fastapi.testclient import TestClient

import main
from config import get_settings

FRONTEND = "https://vendly-frontend.vercel.app"
AJENO = "https://sitio-malicioso.example"

client = TestClient(main.app)


class TestOrigenPermitido:
    """El frontend real sigue pasando; si esto falla, la app deja de funcionar."""

    def test_preflight_del_frontend_recibe_su_propio_origen(self):
        resp = client.options(
            "/",
            headers={"Origin": FRONTEND, "Access-Control-Request-Method": "GET"},
        )
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == FRONTEND

    def test_peticion_simple_del_frontend_recibe_su_propio_origen(self):
        resp = client.get("/", headers={"Origin": FRONTEND})
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == FRONTEND

    def test_el_origen_se_devuelve_explicito_y_nunca_como_comodin(self):
        resp = client.get("/", headers={"Origin": FRONTEND})
        assert resp.headers["access-control-allow-origin"] != "*"


class TestOrigenAjeno:
    """
    Un origen que no esta en la lista no recibe permiso.

    Ojo con lo que significa: el servidor responde 200 y entrega el cuerpo
    igual. Lo que falta es la cabecera, y es el navegador quien entonces se
    niega a entregarle la respuesta al JavaScript que la pidio.
    """

    def test_el_preflight_de_un_origen_ajeno_es_rechazado(self):
        resp = client.options(
            "/",
            headers={"Origin": AJENO, "Access-Control-Request-Method": "GET"},
        )
        assert resp.status_code == 400
        assert "access-control-allow-origin" not in resp.headers

    def test_una_peticion_simple_de_un_origen_ajeno_no_recibe_la_cabecera(self):
        resp = client.get("/", headers={"Origin": AJENO})
        assert "access-control-allow-origin" not in resp.headers


class TestSinCredenciales:
    """
    Vendly no usa cookies: la sesion viaja en Authorization: Bearer, que el
    navegador no adjunta por su cuenta. Con las credenciales apagadas, un
    origen ajeno no puede aprovechar la sesion de nadie ni aunque la lista de
    origenes se equivoque algun dia.
    """

    @pytest.mark.parametrize("origen", [FRONTEND, AJENO])
    def test_ninguna_respuesta_permite_credenciales(self, origen):
        resp = client.get("/", headers={"Origin": origen})
        assert "access-control-allow-credentials" not in resp.headers


class TestElComodinNoVuelve:
    """El guardia. Sin esto, la rama de DEBUG puede reaparecer sin que nadie lo note."""

    def test_la_lista_de_origenes_no_contiene_comodin(self):
        assert "*" not in main.origins

    def test_debug_no_agrega_comodin(self, monkeypatch):
        """
        Reimporta main con DEBUG=true, que es lo que un dia habra en Render
        cuando alguien depure algo. Antes, esa sola variable abria la API.
        """
        monkeypatch.setenv("DEBUG", "true")
        get_settings.cache_clear()
        try:
            recargado = importlib.reload(main)
            assert recargado.settings.DEBUG is True, "el entorno no se aplico"
            assert "*" not in recargado.origins
        finally:
            # Dejar el modulo como estaba: otros tests importan main.app y
            # heredarian un DEBUG=true que no pidieron.
            monkeypatch.undo()
            get_settings.cache_clear()
            importlib.reload(main)
