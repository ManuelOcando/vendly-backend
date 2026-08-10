"""
Diagnostico de red en /health, y que los 429 se registren.

Existe para una decision concreta: como llavear el rate limiting. Medido
contra produccion, el limite de 100/minuto de /health nunca llego a saltar
porque la instancia free sirve ~1 peticion por segundo, asi que no hubo forma
de observar la clave desde fuera. Estos campos la hacen observable.
"""
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

    def test_counts_the_proxy_hops(self, client):
        """
        Cuantos saltos hay decide de que posicion se puede leer la IP real
        cuando no hay una cabecera de confianza.
        """
        red = client.get(
            "/api/v1/health",
            headers={"X-Forwarded-For": "203.0.113.7, 104.23.190.112, 10.192.63.131"},
        ).json()["network"]

        assert red["xff_hops"] == 3

    def test_reports_the_cloudflare_headers(self, client):
        """
        Cloudflare las sobrescribe en cada peticion, asi que son la unica
        fuente de IP de cliente que el cliente no puede fijar el mismo.
        """
        red = client.get(
            "/api/v1/health",
            headers={"CF-Connecting-IP": "203.0.113.7", "CF-Ray": "8f2a-MAD"},
        ).json()["network"]

        assert red["cf_connecting_ip"] == "203.0.113.7"
        assert red["cf_ray"] == "8f2a-MAD"

    def test_a_forged_forwarded_for_is_visible_in_the_report(self, client):
        """
        Medido en produccion: uvicorn confia en el proxy y toma la entrada mas
        a la izquierda de X-Forwarded-For, que es la que fija el cliente. El
        reporte tiene que dejar ver el desfase entre lo que el cliente afirma
        y lo que dice una cabecera de confianza.
        """
        red = client.get(
            "/api/v1/health",
            headers={
                "X-Forwarded-For": "203.0.113.7, 159.26.98.237",
                "CF-Connecting-IP": "159.26.98.237",
            },
        ).json()["network"]

        assert red["x_forwarded_for"].startswith("203.0.113.7")
        assert red["cf_connecting_ip"] == "159.26.98.237"

# El registro de los 429 se cubre en tests/test_rate_limiting.py, junto al
# resto del comportamiento del limitador. Aqui vivio un rato mientras el
# diagnostico era lo unico que habia, y una de sus aserciones se quedo al
# reves: exigia que el manejador fuera una corrutina, y tiene que ser
# sincrono o SlowAPIMiddleware lo descarta.
