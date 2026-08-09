"""
Verificacion de la firma de los webhooks de Meta.

Antes de esto `POST /api/v1/whatsapp/webhook` aceptaba cualquier JSON: la URL
es publica, asi que bastaba con conocerla para inyectar mensajes con el
phone_number_id de cualquier tenant. Los casos de abajo cubren tanto las
funciones puras como el endpoint montado.
"""
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.whatsapp.webhook_security import (
    SIGNATURE_HEADER,
    is_valid_signature,
    sign_payload,
)

APP_SECRET = "s3cr3t-de-la-app-de-meta"
BODY = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode()


class TestIsValidSignature:
    """La funcion pura. Falla cerrado ante cualquier entrada que no cuadre."""

    def test_accepts_the_signature_meta_would_send(self):
        assert is_valid_signature(APP_SECRET, BODY, sign_payload(APP_SECRET, BODY))

    def test_rejects_signature_for_a_different_body(self):
        otro = json.dumps({"object": "otra_cosa"}).encode()
        assert not is_valid_signature(APP_SECRET, BODY, sign_payload(APP_SECRET, otro))

    def test_rejects_signature_made_with_another_secret(self):
        assert not is_valid_signature(
            APP_SECRET, BODY, sign_payload("secreto-del-atacante", BODY)
        )

    def test_rejects_missing_header(self):
        assert not is_valid_signature(APP_SECRET, BODY, None)

    def test_rejects_empty_header(self):
        assert not is_valid_signature(APP_SECRET, BODY, "")

    def test_rejects_header_without_the_sha256_prefix(self):
        firmada = sign_payload(APP_SECRET, BODY)
        assert not is_valid_signature(APP_SECRET, BODY, firmada.removeprefix("sha256="))

    def test_rejects_sha1_prefix(self):
        """Meta tambien manda X-Hub-Signature (sha1); no la aceptamos."""
        firmada = sign_payload(APP_SECRET, BODY).replace("sha256=", "sha1=")
        assert not is_valid_signature(APP_SECRET, BODY, firmada)

    def test_rejects_non_hex_digest_without_raising(self):
        """bytes.fromhex explota con basura: tiene que devolver False, no 500."""
        assert not is_valid_signature(APP_SECRET, BODY, "sha256=no-es-hexadecimal")

    def test_rejects_non_ascii_header_without_raising(self):
        """hmac.compare_digest lanza TypeError con str no-ASCII."""
        assert not is_valid_signature(APP_SECRET, BODY, "sha256=ñoño")

    def test_rejects_everything_when_the_secret_is_not_configured(self):
        """Sin App Secret no hay nada que verificar: se rechaza, no se acepta."""
        assert not is_valid_signature("", BODY, sign_payload(APP_SECRET, BODY))
        assert not is_valid_signature("", BODY, None)


@pytest.fixture
def client(monkeypatch):
    """
    El endpoint real montado, con DEBUG=False (produccion) y un App Secret
    conocido. get_settings esta cacheada con lru_cache, asi que hay que
    limpiarla en ambos sentidos.
    """
    from config import get_settings

    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("META_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("META_WEBHOOK_VERIFY_TOKEN", "token-de-verificacion")
    get_settings.cache_clear()

    from api.v1.whatsapp import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/whatsapp")
    yield TestClient(app)

    get_settings.cache_clear()


class TestWebhookEndpoint:
    def test_unsigned_payload_is_rejected(self, client):
        """El agujero original: un POST a pelo entraba y se procesaba."""
        r = client.post("/api/v1/whatsapp/webhook", content=BODY)
        assert r.status_code == 403

    def test_forged_signature_is_rejected(self, client):
        r = client.post(
            "/api/v1/whatsapp/webhook",
            content=BODY,
            headers={SIGNATURE_HEADER: sign_payload("otro-secreto", BODY)},
        )
        assert r.status_code == 403

    def test_signed_payload_is_accepted(self, client):
        r = client.post(
            "/api/v1/whatsapp/webhook",
            content=BODY,
            headers={SIGNATURE_HEADER: sign_payload(APP_SECRET, BODY)},
        )
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_body_tampered_after_signing_is_rejected(self, client):
        """Firma valida para otro cuerpo: es el caso de replay/manipulacion."""
        firma = sign_payload(APP_SECRET, BODY)
        alterado = json.dumps(
            {"object": "whatsapp_business_account", "entry": [{"changes": []}]}
        ).encode()
        r = client.post(
            "/api/v1/whatsapp/webhook",
            content=alterado,
            headers={SIGNATURE_HEADER: firma},
        )
        assert r.status_code == 403

    def test_rejection_is_a_403_not_a_200_with_error_body(self, client):
        """
        El handler envuelve todo en un try que devuelve 200 {"status": "error"}.
        Si la verificacion cayera dentro, un rechazo pareceria una aceptacion y
        Meta no reintentaria.
        """
        r = client.post("/api/v1/whatsapp/webhook", content=b"{}")
        assert r.status_code == 403
        assert r.json().get("status") != "error"


class TestWebhookVerificationHandshake:
    def test_correct_token_returns_the_challenge(self, client):
        r = client.get(
            "/api/v1/whatsapp/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "token-de-verificacion",
                "hub.challenge": "1158201444",
            },
        )
        assert r.status_code == 200
        assert r.json() == 1158201444

    def test_wrong_token_is_rejected(self, client):
        r = client.get(
            "/api/v1/whatsapp/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "vendly-webhook-secret",
                "hub.challenge": "1158201444",
            },
        )
        assert r.status_code == 403

    def test_non_numeric_challenge_is_a_400_not_a_500(self, client):
        r = client.get(
            "/api/v1/whatsapp/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "token-de-verificacion",
                "hub.challenge": "no-es-un-numero",
            },
        )
        assert r.status_code == 400

    def test_handshake_rejected_when_no_token_is_configured(self, monkeypatch):
        """
        El default era "vendly-webhook-secret", publicado en el repo. Ahora el
        default es vacio, y vacio tiene que rechazar en vez de aceptar.
        """
        from config import get_settings

        monkeypatch.setenv("DEBUG", "false")
        monkeypatch.setenv("META_WEBHOOK_VERIFY_TOKEN", "")
        get_settings.cache_clear()

        from api.v1.whatsapp import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1/whatsapp")

        r = TestClient(app).get(
            "/api/v1/whatsapp/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "",
                "hub.challenge": "123",
            },
        )
        assert r.status_code == 403
        get_settings.cache_clear()


class TestDebugBypass:
    def test_local_curl_still_works_with_debug_true(self, monkeypatch):
        """
        La guia de testing documenta simular el webhook con curl, que no puede
        firmar. Ese atajo solo puede existir con DEBUG=True.
        """
        from config import get_settings

        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.setenv("META_APP_SECRET", "")
        get_settings.cache_clear()

        from api.v1.whatsapp import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1/whatsapp")

        r = TestClient(app).post("/api/v1/whatsapp/webhook", content=BODY)
        assert r.status_code == 200
        get_settings.cache_clear()
