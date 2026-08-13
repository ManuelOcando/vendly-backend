"""
Datos de cobro del vendedor: el hueco donde el bot se quedaba callado.

Al confirmar un pedido el cliente recibia "contacta al vendedor para recibir las
instrucciones de pago" y tenia que preguntar, justo en el momento mas fragil de
la venta. La fontaneria estaba: el handler ya leia bot_configurations. Lo que no
habia era forma de escribirla -- ni endpoint, ni formulario, ni una sola fila en
la tabla (cero en produccion el 13/08/2026).

El ultimo bloque vigila la trampa que habia debajo: el DEFAULT de la columna
payment_instructions traia marcadores que nadie sustituye.
"""
import pytest
from fastapi.testclient import TestClient

import main
from api.deps import get_current_tenant
from services.i18n import t
from services.payment_instructions import compose, tiene_datos

TENANT = {"id": "tenant-abc"}

COMPLETO = {
    "bank": "Banesco",
    "id_number": "V-12345678",
    "phone": "0412-1234567",
    "notes": "",
}


@pytest.fixture
def cliente():
    main.app.dependency_overrides[get_current_tenant] = lambda: TENANT
    yield TestClient(main.app, raise_server_exceptions=False)
    main.app.dependency_overrides.clear()


class TestElMensajeCompuesto:
    def test_lleva_los_tres_datos(self):
        mensaje = compose(COMPLETO, 12.50, "es")
        assert "Banesco" in mensaje
        assert "V-12345678" in mensaje
        assert "0412-1234567" in mensaje

    def test_se_compone_en_el_idioma_del_cliente(self):
        """
        El vendedor es venezolano y el cliente puede no serlo. Por eso esto se
        compone al enviar y no al guardar: un texto montado al guardar quedaria
        clavado en el idioma del vendedor.
        """
        assert "Banco:" in compose(COMPLETO, 10.0, "es")
        assert "Bank:" in compose(COMPLETO, 10.0, "en")
        assert "Documento:" in compose(COMPLETO, 10.0, "pt")

    def test_no_repite_el_total(self):
        """El mensaje de confirmacion ya lleva 'Total: $X' dos lineas arriba."""
        assert compose(COMPLETO, 12.50, "es").count("12.50") == 0

    def test_las_notas_solas_bastan(self):
        """Quien cobra en efectivo o por Zelle no rellena los campos bancarios."""
        mensaje = compose({"notes": "Efectivo al recibir."}, 10.0, "es")
        assert "Efectivo al recibir." in mensaje

    def test_sin_datos_cae_al_texto_de_siempre(self):
        assert compose({}, 10.0, "es") == t("order.payment_default", "es")
        assert compose(None, 10.0, "es") == t("order.payment_default", "es")

    def test_respeta_un_texto_escrito_a_mano(self):
        """Compatibilidad: algun tenant pudo escribir payment_instructions."""
        assert compose({}, 10.0, "es", legacy_text="Pásame el pago por Zelle") == (
            "Pásame el pago por Zelle"
        )

    def test_payment_info_gana_al_texto_heredado(self):
        mensaje = compose(COMPLETO, 10.0, "es", legacy_text="viejo")
        assert "Banesco" in mensaje and "viejo" not in mensaje

    def test_los_espacios_sobrantes_no_crean_lineas_vacias(self):
        mensaje = compose({"bank": "  ", "phone": " 0412 "}, 10.0, "es")
        assert "Banco:" not in mensaje
        assert "0412" in mensaje


class TestElEndpoint:
    def test_sin_autenticacion_401(self):
        main.app.dependency_overrides.clear()
        assert TestClient(main.app).get("/api/v1/bot-config").status_code == 401

    def test_get_sin_fila_devuelve_vacios_y_no_escribe(self, cliente, monkeypatch):
        escrituras = []
        _fake_db(monkeypatch, filas=[], escrituras=escrituras)

        resp = cliente.get("/api/v1/bot-config")

        assert resp.status_code == 200
        assert resp.json()["configured"] is False
        assert resp.json()["payment_info"]["bank"] == ""
        assert escrituras == [], "un GET no debe crear la fila"

    def test_put_crea_la_fila_la_primera_vez(self, cliente, monkeypatch):
        escrituras = []
        _fake_db(monkeypatch, filas=[], escrituras=escrituras)

        resp = cliente.put("/api/v1/bot-config", json={"payment_info": COMPLETO})

        assert resp.status_code == 200
        assert [op for op, _ in escrituras] == ["insert"]

    def test_put_actualiza_si_ya_existe(self, cliente, monkeypatch):
        escrituras = []
        _fake_db(monkeypatch, filas=[{"id": "bc-1"}], escrituras=escrituras)

        cliente.put("/api/v1/bot-config", json={"payment_info": COMPLETO})

        assert [op for op, _ in escrituras] == ["update"]

    def test_el_put_devuelve_la_vista_previa(self, cliente, monkeypatch):
        _fake_db(monkeypatch, filas=[], escrituras=[])
        resp = cliente.put("/api/v1/bot-config", json={"payment_info": COMPLETO})
        assert "Banesco" in resp.json()["preview"]

    def test_rechaza_campos_desmesurados(self, cliente, monkeypatch):
        _fake_db(monkeypatch, filas=[], escrituras=[])
        resp = cliente.put(
            "/api/v1/bot-config",
            json={"payment_info": {**COMPLETO, "bank": "x" * 200}},
        )
        assert resp.status_code == 422


class TestLaTrampaDeLosMarcadores:
    """
    payment_instructions tenia como DEFAULT en la base un texto con {bank},
    {ci} y {phone}. Nadie los sustituye: t() formatea la plantilla una vez, y lo
    que va dentro del valor insertado no se vuelve a formatear. Una fila creada
    sin fijar esa columna le mandaba las llaves literales al cliente.
    """

    def test_el_put_siempre_fija_payment_instructions(self, cliente, monkeypatch):
        """Aunque la migracion 023 no este aplicada, el default no puede entrar."""
        escrituras = []
        _fake_db(monkeypatch, filas=[], escrituras=escrituras)

        cliente.put("/api/v1/bot-config", json={"payment_info": COMPLETO})

        _, payload = escrituras[0]
        assert "payment_instructions" in payload
        assert payload["payment_instructions"] == ""

    def test_la_migracion_quita_el_default(self):
        from pathlib import Path

        sql = (
            Path(__file__).resolve().parent.parent
            / "db" / "migrations" / "023_drop_payment_instructions_default.sql"
        ).read_text(encoding="utf-8")
        assert "DROP DEFAULT" in sql
        assert "payment_instructions" in sql

    @pytest.mark.parametrize("info", [COMPLETO, {"notes": "Efectivo"}, {}, None])
    def test_el_mensaje_nunca_lleva_marcadores_sin_sustituir(self, info):
        """
        El guardia. Es el fallo concreto que producia la trampa, y el que
        producira cualquier plantilla nueva a la que se le olvide un parametro.
        """
        for idioma in ("es", "en", "pt"):
            bloque = compose(info, 12.50, idioma)
            completo = t(
                "order.confirmed", idioma,
                order_ref="abc12345", total="12.50", payment_instructions=bloque,
            )
            assert "{" not in completo, f"marcador sin sustituir en {idioma}: {completo}"


class TestTieneDatos:
    @pytest.mark.parametrize("info,esperado", [
        (COMPLETO, True),
        ({"notes": "algo"}, True),
        ({"bank": "   "}, False),
        ({}, False),
        (None, False),
    ])
    def test_detecta_si_el_vendedor_lleno_algo(self, info, esperado):
        assert tiene_datos(info) is esperado


def _fake_db(monkeypatch, filas, escrituras):
    """Un cliente de Supabase que solo modela lo que este endpoint usa."""
    from unittest.mock import Mock

    def tabla(_nombre):
        q = Mock()
        q.select.return_value.eq.return_value.limit.return_value.execute.return_value = Mock(data=filas)

        def insert(payload):
            escrituras.append(("insert", payload))
            return Mock(execute=Mock(return_value=Mock(data=[payload])))

        def update(payload):
            escrituras.append(("update", payload))
            return Mock(eq=Mock(return_value=Mock(execute=Mock(return_value=Mock(data=[payload])))))

        q.insert.side_effect = insert
        q.update.side_effect = update
        return q

    db = Mock()
    db.table.side_effect = tabla
    monkeypatch.setattr("api.v1.bot_config.get_supabase_client", lambda: db)
    return db
