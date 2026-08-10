"""
Cache de las comprobaciones de dependencias en /health.

/health es publico y hace una consulta a Supabase y un ida y vuelta a Redis en
cada llamada. Medido contra produccion: 130 peticiones con 25 en paralelo
tardaron 127 segundos, ~1 por segundo, sin que el limite de 100/minuto llegara
a dispararse. Sin cache el endpoint es un amplificador gratis contra la base.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# El cache se vacia entre tests desde tests/conftest.py, que lo hace para toda
# la suite: ya son tres los archivos que llaman a /health.


@pytest.fixture
def entorno():
    """Devuelve (client, db, redis) para poder contar los accesos reales."""
    from api.v1.health import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    from middleware.rate_limiter import limiter
    from slowapi.errors import RateLimitExceeded
    from slowapi import _rate_limit_exceeded_handler

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    db = MagicMock()
    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value="ok")

    with patch("api.v1.health.get_supabase_client", return_value=db), patch(
        "api.v1.health.get_redis_client", return_value=redis
    ):
        yield TestClient(app), db, redis


class TestCache:
    def test_repeated_calls_hit_the_database_once(self, entorno):
        client, db, redis = entorno

        for _ in range(10):
            client.get("/api/v1/health")

        assert db.table.call_count == 1
        assert redis.set.await_count == 1

    def test_the_first_call_reports_a_fresh_check(self, entorno):
        client, _, _ = entorno
        assert client.get("/api/v1/health").json()["checks_age_seconds"] == 0.0

    def test_later_calls_report_the_age(self, entorno):
        """Quien monitoriza tiene que poder ver que el dato viene de cache."""
        client, _, _ = entorno
        client.get("/api/v1/health")

        import api.v1.health as h

        h._dependency_cache["at"] -= 7  # envejecer sin dormir el test
        assert client.get("/api/v1/health").json()["checks_age_seconds"] >= 7

    def test_the_cache_expires(self, entorno):
        client, db, _ = entorno
        client.get("/api/v1/health")

        import api.v1.health as h

        h._dependency_cache["at"] -= h._DEPENDENCY_TTL_SECONDS + 1
        client.get("/api/v1/health")

        assert db.table.call_count == 2

    def test_results_still_reach_the_response(self, entorno):
        """Cachear no puede significar dejar de informar."""
        client, _, _ = entorno
        cuerpo = client.get("/api/v1/health").json()

        assert cuerpo["supabase"] == "connected"
        assert cuerpo["redis"] == "connected"
        assert cuerpo["status"] == "ok"

    def test_a_failure_is_cached_too_but_still_degrades(self, entorno):
        client, db, _ = entorno
        db.table.side_effect = RuntimeError("sin conexion")

        primero = client.get("/api/v1/health").json()
        segundo = client.get("/api/v1/health").json()

        assert primero["status"] == "degraded"
        assert segundo["status"] == "degraded"
        assert "error" in segundo["supabase"]


class TestWhatIsNotCached:
    def test_the_network_block_is_per_request(self, entorno):
        """
        Depende de quien pregunta. Cachearlo le devolveria a un cliente la
        direccion de otro, que ademas seria una fuga.
        """
        client, _, _ = entorno

        uno = client.get(
            "/api/v1/health", headers={"CF-Connecting-IP": "203.0.113.7"}
        ).json()["network"]
        dos = client.get(
            "/api/v1/health", headers={"CF-Connecting-IP": "198.51.100.9"}
        ).json()["network"]

        assert uno["cf_connecting_ip"] == "203.0.113.7"
        assert dos["cf_connecting_ip"] == "198.51.100.9"


class TestStampede:
    def test_concurrent_misses_only_check_once(self):
        """
        Bajo inundacion, sin candado todas las peticiones que llegan con el
        cache vencido salen a la base a la vez - justo cuando menos conviene.
        """
        import api.v1.health as h

        db = MagicMock()
        redis = MagicMock()

        async def set_lento(*a, **k):
            await asyncio.sleep(0.05)
            return True

        redis.set = AsyncMock(side_effect=set_lento)
        redis.get = AsyncMock(return_value="ok")

        async def veinte_a_la_vez():
            with patch("api.v1.health.get_supabase_client", return_value=db), patch(
                "api.v1.health.get_redis_client", return_value=redis
            ):
                await asyncio.gather(*(h._dependency_checks() for _ in range(20)))

        asyncio.run(veinte_a_la_vez())

        assert db.table.call_count == 1
