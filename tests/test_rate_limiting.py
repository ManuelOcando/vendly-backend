"""
Rate limiting: la clave, la cobertura y el registro.

Antes de esto solo /health tenia limite, y estaba llaveado por un valor que el
cliente elige. Medido contra produccion: mandando `X-Forwarded-For: 203.0.113.7`
la clave del limitador pasaba a ser 203.0.113.7, asi que cualquier limite se
evadia variando una cabecera por peticion. CF-Connecting-IP no: Cloudflare la
sobrescribe, y un intento de mandarla desde fuera se corta con 403 en el borde.
"""
import logging
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from slowapi import Limiter

from middleware.rate_limiter import (
    DEFAULT_LIMITS,
    client_ip,
    limiter,
    rate_limit_exception_handler,
)


@pytest.fixture
def app():
    """
    Limitador propio por test, con la misma configuracion que el real.

    Reutilizar el singleton de middleware.rate_limiter no sirve: su
    almacenamiento en memoria y su registro de rutas persisten en el proceso,
    y la fixture volveria a registrar el decorador sobre una funcion con el
    mismo nombre cualificado en cada test. Las copias del limite se acumulan y
    una sola peticion descuenta varias veces, asi que los tests se contaminan
    entre si segun el orden en que corran.
    """
    test_limiter = Limiter(key_func=client_ip, default_limits=DEFAULT_LIMITS)

    app = FastAPI()
    app.state.limiter = test_limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/sin-decorar")
    async def sin_decorar():
        return {"ok": True}

    @app.get("/estrecho")
    @test_limiter.limit("3/minute")
    async def estrecho(request: Request):
        return {"ok": True}

    return app


def _get(client, path, ip, **headers):
    headers["CF-Connecting-IP"] = ip
    return client.get(path, headers=headers)


class TestTheKeyCannotBeChosenByTheCaller:
    def test_cf_connecting_ip_is_the_key(self):
        request = MagicMock()
        request.headers = {"cf-connecting-ip": "159.26.98.237"}
        assert client_ip(request) == "159.26.98.237"

    def test_forwarded_for_does_not_override_cf_connecting_ip(self, app):
        """
        El agujero exacto que se midio: cambiar X-Forwarded-For movia de cubo.
        Con la clave nueva, agotado el limite sigue agotado.
        """
        client = TestClient(app)
        for _ in range(3):
            _get(client, "/estrecho", "7.7.7.7")

        agotado = _get(client, "/estrecho", "7.7.7.7", **{"X-Forwarded-For": "1.2.3.4"})
        assert agotado.status_code == 429

    def test_different_clients_get_different_buckets(self, app):
        """
        Lo contrario tambien importa: si todos compartieran cubo, un limite
        estrangularia a los clientes legitimos entre si.
        """
        client = TestClient(app)
        for _ in range(4):
            _get(client, "/estrecho", "9.9.9.9")

        assert _get(client, "/estrecho", "9.9.9.9").status_code == 429
        assert _get(client, "/estrecho", "8.8.8.8").status_code == 200

    def test_falls_back_when_cloudflare_header_is_absent(self):
        """Desarrollo local y rutas que no pasan por el borde."""
        request = MagicMock()
        request.headers = {}
        request.client.host = "127.0.0.1"
        request.url.path = "/x"
        assert client_ip(request) == "127.0.0.1"


class TestCoverage:
    def test_an_undecorated_route_is_still_limited(self, app):
        """
        El motivo de usar SlowAPIMiddleware con default_limits en vez de ir
        decorando: 22 rutas publicas se habian quedado sin limite, y la
        proxima que se añada tampoco lo tendria.
        """
        client = TestClient(app)
        assert _get(client, "/sin-decorar", "5.5.5.5").status_code == 200

        limite = int(DEFAULT_LIMITS[0].split("/")[0])
        for _ in range(limite):
            _get(client, "/sin-decorar", "6.6.6.6")

        assert _get(client, "/sin-decorar", "6.6.6.6").status_code == 429

    def test_an_explicit_limit_replaces_the_default(self, app):
        """
        slowapi usa override_defaults=True, asi que la ruta decorada corre solo
        con su limite. Si se sumaran, el global mandaria y el decorador seria
        decorativo.
        """
        client = TestClient(app)
        codigos = [_get(client, "/estrecho", "4.4.4.4").status_code for _ in range(5)]
        assert codigos == [200, 200, 200, 429, 429]

    def test_the_webhook_carries_its_own_limit(self):
        """
        El endpoint mas caro de todos: dispara el LLM, escribe en la base y
        manda WhatsApps con el token del tenant.
        """
        import main  # registra las rutas en el limitador real

        registradas = limiter._route_limits
        clave = "api.v1.whatsapp.whatsapp_webhook"

        assert clave in registradas, "el webhook perdio su limite propio"
        assert [str(l.limit) for l in registradas[clave]] == ["300 per 1 minute"]


class TestHitsAreLogged:
    def test_the_handler_is_synchronous(self):
        """
        SlowAPIMiddleware descarta el manejador registrado si es corrutina
        ("cannot execute asynchronous code in a synchronous middleware") y cae
        al de slowapi. Siendo async, los 429 del limite global no dejarian
        rastro - que era justo el bug que se venia a arreglar.
        """
        import inspect

        assert not inspect.iscoroutinefunction(rate_limit_exception_handler)

    def test_a_middleware_triggered_429_is_logged(self, app, caplog):
        client = TestClient(app)
        for _ in range(3):
            _get(client, "/estrecho", "3.3.3.3")

        with caplog.at_level(logging.WARNING, logger="middleware.rate_limiter"):
            _get(client, "/estrecho", "3.3.3.3")

        assert "Rate limit alcanzado" in caplog.text
        assert "3.3.3.3" in caplog.text
        assert "/estrecho" in caplog.text
