"""
El LLM en /health.

Motivado por un apagon real: al rotar la clave de Gemini se perdio el acceso al
modelo, y el unico sintoma fue que los clientes recibian una disculpa por
WhatsApp. Nada en /health lo delataba. Estos casos fijan que ahora si.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """
    Supabase y Redis quedan sanos y en memoria. Sin esto los tests salen a la
    produccion real (21s por corrida) y, peor, cualquiera de los dos cayendo
    degradaria el status y haria pasar por buenas las aserciones sobre el LLM.
    """
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

    # /health/llm exige sesion; aqui damos una para probar el cuerpo, y
    # TestDeepProbeRequiresAuth comprueba aparte que sin ella no pasa.
    from api.v1.health import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"id": "u1"}

    with patch("api.v1.health.get_supabase_client", return_value=MagicMock()), patch(
        "api.v1.health.get_redis_client", return_value=redis
    ):
        yield TestClient(app)


def _settings(**overrides):
    base = {
        "APP_NAME": "Vendly API",
        "APP_VERSION": "0.1.0",
        "DEBUG": False,
        "LLM_ENABLED": True,
        "LLM_PROVIDER": "gemini",
        "GEMINI_MODEL": "gemini-3.6-flash",
        "GEMINI_API_KEY": "una-clave",
        "OPENROUTER_MODEL": "qwen/qwen-3.5b-instruct",
        "OPENROUTER_API_KEY": "",
    }
    base.update(overrides)
    return MagicMock(**base)


class TestLLMBlockInHealth:
    def test_reports_provider_and_model(self, client):
        with patch("api.v1.health.get_settings", return_value=_settings()), patch(
            "services.llm.factory.get_llm_provider", return_value=MagicMock()
        ):
            llm = client.get("/api/v1/health").json()["llm"]

        assert llm["provider"] == "gemini"
        assert llm["model"] == "gemini-3.6-flash"
        assert llm["enabled"] is True

    def test_never_exposes_the_api_key(self, client):
        """
        Solo present/missing. gemini_provider ya loguea un prefijo de la clave;
        un endpoint publico no va a repetir el error.
        """
        with patch(
            "api.v1.health.get_settings",
            return_value=_settings(GEMINI_API_KEY="AQ.clave-secreta-de-verdad"),
        ), patch("services.llm.factory.get_llm_provider", return_value=MagicMock()):
            cuerpo = client.get("/api/v1/health").text

        assert "AQ.clave-secreta-de-verdad" not in cuerpo
        assert '"api_key":"present"' in cuerpo.replace(" ", "")

    def test_missing_key_is_reported_and_degrades(self, client):
        with patch(
            "api.v1.health.get_settings", return_value=_settings(GEMINI_API_KEY="")
        ), patch("services.llm.factory.get_llm_provider", return_value=None):
            cuerpo = client.get("/api/v1/health").json()

        assert cuerpo["llm"]["api_key"] == "missing"
        assert cuerpo["status"] == "degraded"

    def test_disabled_llm_is_not_a_degradation(self, client):
        """Apagarlo a proposito no es un fallo."""
        with patch(
            "api.v1.health.get_settings", return_value=_settings(LLM_ENABLED=False)
        ):
            cuerpo = client.get("/api/v1/health").json()

        assert cuerpo["llm"]["enabled"] is False
        assert cuerpo["status"] != "degraded"

    def test_openrouter_reports_its_own_model_and_key(self, client):
        with patch(
            "api.v1.health.get_settings",
            return_value=_settings(LLM_PROVIDER="openrouter", OPENROUTER_API_KEY="k"),
        ), patch("services.llm.factory.get_llm_provider", return_value=MagicMock()):
            llm = client.get("/api/v1/health").json()["llm"]

        assert llm["model"] == "qwen/qwen-3.5b-instruct"
        assert llm["api_key"] == "present"

    def test_health_does_not_call_the_model(self, client):
        """Render pega a /health constantemente; generar ahi seria cuota tirada."""
        provider = MagicMock()
        provider.generate_response = AsyncMock(return_value={"ok": True})

        with patch("api.v1.health.get_settings", return_value=_settings()), patch(
            "services.llm.factory.get_llm_provider", return_value=provider
        ):
            client.get("/api/v1/health")

        provider.generate_response.assert_not_called()


class TestDeepProbe:
    def test_reports_ok_and_latency_on_a_real_round_trip(self, client):
        provider = MagicMock()
        provider.generate_response = AsyncMock(return_value={"ok": True})

        with patch("api.v1.health.get_settings", return_value=_settings()), patch(
            "services.llm.factory.get_llm_provider", return_value=provider
        ):
            cuerpo = client.get("/api/v1/health/llm").json()

        assert cuerpo["status"] == "ok"
        assert isinstance(cuerpo["latency_ms"], int)
        provider.generate_response.assert_called_once()

    def test_surfaces_the_retired_model_error(self, client):
        """
        El apagon exacto: clave valida, proveedor construido, y el 404 solo
        aparece al generar. El texto del proveedor tiene que llegar entero.
        """
        provider = MagicMock()
        provider.generate_response = AsyncMock(
            side_effect=RuntimeError(
                "404 models/gemini-2.5-flash is no longer available to new users"
            )
        )

        with patch("api.v1.health.get_settings", return_value=_settings()), patch(
            "services.llm.factory.get_llm_provider", return_value=provider
        ):
            cuerpo = client.get("/api/v1/health/llm").json()

        assert cuerpo["status"] == "error"
        assert cuerpo["stage"] == "generate"
        assert "no longer available to new users" in cuerpo["error"]

    def test_none_from_the_provider_is_an_error_not_an_ok(self, client):
        """
        generate_response se traga sus excepciones y devuelve None. Sin esta
        rama la sonda diria "ok" justo ante el fallo que la motivo.
        """
        provider = MagicMock()
        provider.generate_response = AsyncMock(return_value=None)

        with patch("api.v1.health.get_settings", return_value=_settings()), patch(
            "services.llm.factory.get_llm_provider", return_value=provider
        ):
            cuerpo = client.get("/api/v1/health/llm").json()

        assert cuerpo["status"] == "error"
        assert cuerpo["stage"] == "generate"

    def test_disabled_llm_short_circuits(self, client):
        with patch(
            "api.v1.health.get_settings", return_value=_settings(LLM_ENABLED=False)
        ):
            cuerpo = client.get("/api/v1/health/llm").json()

        assert cuerpo["status"] == "disabled"

    def test_provider_filler_is_an_error_not_an_ok(self, client):
        """
        El proveedor devuelve un relleno con forma de respuesta valida cuando
        no puede parsear su propia salida. La primera version de esta sonda lo
        daba por bueno - se vio en una prueba real contra Gemini.
        """
        provider = MagicMock()
        provider.generate_response = AsyncMock(
            return_value={
                "llm_error": True,
                "intention": "other",
                "response_text": "Disculpa, hubo un error. ¿Puedes repetir tu pedido?",
                "products": [],
                "questions": [],
            }
        )

        with patch("api.v1.health.get_settings", return_value=_settings()), patch(
            "services.llm.factory.get_llm_provider", return_value=provider
        ):
            cuerpo = client.get("/api/v1/health/llm").json()

        assert cuerpo["status"] == "error"
        assert cuerpo["stage"] == "parse"

    def test_probe_leaves_room_for_thinking_tokens(self, client):
        """
        Con max_tokens=32 la sonda se autoinfligia un finish_reason=MAX_TOKENS
        contra un modelo que razona antes de emitir: el fallo parecia del
        modelo y lo causaba la sonda.
        """
        provider = MagicMock()
        provider.generate_response = AsyncMock(return_value={"ok": True})

        with patch("api.v1.health.get_settings", return_value=_settings()), patch(
            "services.llm.factory.get_llm_provider", return_value=provider
        ):
            client.get("/api/v1/health/llm")

        assert provider.generate_response.call_args.kwargs["max_tokens"] >= 256


class TestDeepProbeRequiresAuth:
    """
    /health es publico; la sonda profunda no puede serlo. Cada llamada gasta
    cuota, y un endpoint anonimo que gasta dinero es un grifo abierto.
    """

    def test_anonymous_cannot_spend_llm_quota(self):
        from api.v1.health import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        provider = MagicMock()
        provider.generate_response = AsyncMock(return_value={"ok": True})

        with patch("api.v1.health.get_settings", return_value=_settings()), patch(
            "services.llm.factory.get_llm_provider", return_value=provider
        ):
            r = TestClient(app).get("/api/v1/health/llm")

        assert r.status_code == 401
        provider.generate_response.assert_not_called()

    def test_plain_health_stays_public(self):
        """El monitoreo automatico tiene que poder seguir pegandole."""
        from api.v1.health import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        redis = MagicMock()
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value="ok")

        with patch("api.v1.health.get_settings", return_value=_settings()), patch(
            "api.v1.health.get_supabase_client", return_value=MagicMock()
        ), patch("api.v1.health.get_redis_client", return_value=redis), patch(
            "services.llm.factory.get_llm_provider", return_value=MagicMock()
        ):
            r = TestClient(app).get("/api/v1/health")

        assert r.status_code == 200
