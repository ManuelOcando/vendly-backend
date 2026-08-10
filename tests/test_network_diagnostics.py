"""
Diagnostico de red en /health, y que los 429 se registren.

Existe para una decision concreta: como llavear el rate limiting. Medido
contra produccion, el limite de 100/minuto de /health nunca llego a saltar
porque la instancia free sirve ~1 peticion por segundo, asi que no hubo forma
de observar la clave desde fuera. Estos campos la hacen observable.
"""
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.v1.health import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    from middleware.rate_limiter import limiter
    from slowapi.errors import RateLimitExceeded
    from slowapi import _rate_limit_exceeded_handler

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value="ok")

    with patch("api.v1.health.get_supabase_client", return_value=MagicMock()), patch(
        "api.v1.health.get_redis_client", return_value=redis
    ):
        yield TestClient(app)


class TestNetworkReport:
    def test_reports_the_key_the_limiter_would_use(self, client):
        red = client.get("/api/v1/health").json()["network"]

        # El discriminante: rate_limit_key sale de get_remote_address, que
        # devuelve request.client.host. Si algun dia divergen, es que un
        # middleware reescribio request.client - justo lo que buscamos saber.
        assert red["rate_limit_key"] == red["client_host"]

    def test_echoes_the_proxy_headers_verbatim(self, client):
        red = client.get(
            "/api/v1/health",
            headers={"X-Forwarded-For": "203.0.113.7, 70.41.3.18", "X-Real-IP": "203.0.113.7"},
        ).json()["network"]

        assert red["x_forwarded_for"] == "203.0.113.7, 70.41.3.18"
        assert red["x_real_ip"] == "203.0.113.7"

    def test_absent_headers_are_null_not_missing(self, client):
        """Distinguir "el proxy no mando nada" de "el campo no existe"."""
        red = client.get("/api/v1/health").json()["network"]

        assert "x_forwarded_for" in red
        assert red["x_forwarded_for"] is None

    def test_headers_do_not_change_the_key_today(self, client):
        """
        Deja constancia del comportamiento actual: get_remote_address ignora
        X-Forwarded-For por completo. Si esto empieza a fallar es que se
        cambio la key_func o se activaron las cabeceras de proxy, y entonces
        los limites por IP pasan a ser falsificables si no se validan.
        """
        sin = client.get("/api/v1/health").json()["network"]["rate_limit_key"]
        con = client.get(
            "/api/v1/health", headers={"X-Forwarded-For": "198.51.100.9"}
        ).json()["network"]["rate_limit_key"]

        assert sin == con


class TestRateLimitHitsAreLogged:
    def test_the_handler_logs_before_responding(self, caplog):
        """
        Antes, main.py registraba el manejador pelado de slowapi y el envoltorio
        con logging era codigo muerto: los 429 no dejaban rastro.
        """
        import asyncio

        from middleware.rate_limiter import rate_limit_exception_handler
        from slowapi.errors import RateLimitExceeded

        request = MagicMock()
        request.url.path = "/api/v1/whatsapp/webhook"
        request.client.host = "203.0.113.7"

        exc = MagicMock(spec=RateLimitExceeded)
        exc.detail = "5 per 1 minute"

        with caplog.at_level(logging.WARNING, logger="middleware.rate_limiter"), patch(
            "middleware.rate_limiter._rate_limit_exceeded_handler",
            return_value="respuesta",
        ):
            resultado = asyncio.run(rate_limit_exception_handler(request, exc))

        assert resultado == "respuesta"
        assert "Rate limit alcanzado" in caplog.text
        assert "/api/v1/whatsapp/webhook" in caplog.text
        assert "203.0.113.7" in caplog.text

    def test_main_registers_the_logging_handler(self):
        """El envoltorio solo sirve si es el que esta enchufado."""
        import inspect

        import main

        fuente = inspect.getsource(main)
        assert "rate_limit_exception_handler" in fuente

        from middleware.rate_limiter import rate_limit_exception_handler

        assert inspect.iscoroutinefunction(rate_limit_exception_handler)
