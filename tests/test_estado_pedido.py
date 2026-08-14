"""
El estado del pedido: un dueño, siete claves, ningun hueco.

Los tres fallos de la tarde del 13/08/2026 tienen aqui su caso, porque este
modulo existe por ellos:

  1. el pedido encogia de $50 a $10 al añadir un producto
  2. lo mismo por la otra rama del LLM
  3. cancelar dejaba vivos los pendientes, y volvian despues

El ultimo bloque es el guardia: nadie fuera de estado_pedido.py escribe esas
claves. Es lo que impide que se abra la casilla siguiente.
"""
import re
from pathlib import Path

import pytest

from services.whatsapp.estado_pedido import (
    EstadoPedido,
    Linea,
    a_lineas,
    a_session_data,
    añadir,
    confirmar,
    descartar,
    leer,
    proponer,
    quitar,
    vaciar,
)

HAMBURGUESA = Linea("h", "hamburguesa", 10.0, 1)
SIN_CEBOLLA = Linea("h", "hamburguesa", 10.0, 1, ("sin cebolla",))
PERRO = Linea("p", "perro caliente", 10.0, 2)


class TestLeerLoQueHayEscritoHoy:
    def test_las_dos_formas_de_item(self):
        """La tienda web usa item_id; la conversacion, product_id."""
        de_redis = a_lineas([{"item_id": "h", "name": "hamburguesa",
                              "price": 10.0, "quantity": 2}])
        de_sesion = a_lineas([{"product_id": "h", "name": "hamburguesa",
                               "price": 10.0, "quantity": 2}])
        assert de_redis == de_sesion

    def test_la_clave_antigua_en_singular(self):
        """Quedan sesiones con pending_product, sin la s."""
        estado = leer({"pending_product": {"product_id": "h", "name": "hamburguesa",
                                           "price": 10.0, "quantity": 1}})
        assert len(estado.pendientes) == 1

    def test_una_sesion_vacia_no_revienta(self):
        for datos in (None, {}, {"cart": None}):
            assert leer(datos) == EstadoPedido()

    def test_un_item_corrupto_se_descarta_sin_tumbar_el_resto(self):
        lineas = a_lineas([
            {"product_id": "h", "name": "hamburguesa", "price": "no-es-un-precio"},
            {"product_id": "p", "name": "perro", "price": 10.0, "quantity": 1},
        ])
        assert [l.nombre for l in lineas] == ["perro"]


class TestProponerAcumula:
    """Fallo 1: el pedido encogia de $50 a $10."""

    def test_lo_nuevo_se_suma_a_lo_pendiente(self):
        estado = proponer(EstadoPedido(), [HAMBURGUESA, PERRO])
        assert estado.total_pendiente == 30.0

        estado = proponer(estado, [SIN_CEBOLLA])

        assert estado.total_pendiente == 40.0
        assert len(estado.pendientes) == 3

    def test_deja_esperando_confirmacion(self):
        assert proponer(EstadoPedido(), [HAMBURGUESA]).esperando_confirmacion


class TestAñadirNoPierdeLoPendiente:
    """Fallo 2: la otra rama del LLM ignoraba los pendientes."""

    def test_lo_pendiente_entra_al_carrito_antes_que_lo_nuevo(self):
        estado = proponer(EstadoPedido(), [HAMBURGUESA, PERRO])   # $30 pendientes

        estado = añadir(estado, [SIN_CEBOLLA])                    # + $10

        assert estado.total == 40.0
        assert estado.pendientes == ()
        assert not estado.esperando_confirmacion


class TestVaciarNoDejaNadaVivo:
    """Fallo 3: cancelar dejaba los pendientes, y resucitaban."""

    def test_se_va_todo(self):
        estado = añadir(proponer(EstadoPedido(), [HAMBURGUESA]), [PERRO])
        assert not vaciar(estado).carrito
        assert not vaciar(estado).pendientes

    def test_cancelar_y_pedir_otra_cosa_no_resucita_el_pedido(self):
        """El encadenado exacto que fallaba."""
        estado = proponer(EstadoPedido(), [HAMBURGUESA, PERRO])
        estado = vaciar(estado)
        estado = añadir(estado, [SIN_CEBOLLA])

        assert estado.total == 10.0, "volvio el pedido cancelado"


class TestCuandoDosLineasSonLaMisma:
    def test_mismo_producto_y_modificaciones_suman(self):
        estado = proponer(proponer(EstadoPedido(), [HAMBURGUESA]), [HAMBURGUESA])
        assert len(estado.pendientes) == 1
        assert estado.pendientes[0].cantidad == 2

    def test_modificaciones_distintas_no_se_funden(self):
        estado = proponer(proponer(EstadoPedido(), [HAMBURGUESA]), [SIN_CEBOLLA])
        assert len(estado.pendientes) == 2


class TestConfirmarYDescartar:
    def test_confirmar_pasa_lo_pendiente_al_carrito(self):
        estado = confirmar(proponer(EstadoPedido(), [HAMBURGUESA, PERRO]))
        assert estado.total == 30.0
        assert estado.pendientes == ()

    def test_descartar_tira_lo_pendiente_y_respeta_el_carrito(self):
        estado = añadir(EstadoPedido(), [HAMBURGUESA])
        estado = descartar(proponer(estado, [PERRO]))

        assert estado.total == 10.0
        assert estado.pendientes == ()


class TestQuitar:
    """La operacion que faltaba: "Funcion de remover productos en desarrollo"."""

    def test_saca_del_carrito_lo_pedido(self):
        estado = añadir(EstadoPedido(), [HAMBURGUESA, PERRO])

        estado, quitadas = quitar(estado, "perro caliente")

        assert estado.total == 10.0
        assert [l.nombre for l in quitadas] == ["perro caliente"]

    def test_encuentra_por_parte_del_nombre(self):
        estado = añadir(EstadoPedido(), [Linea("f", "Papas fritas", 5.0, 1)])
        estado, quitadas = quitar(estado, "papas")
        assert len(quitadas) == 1

    def test_quitar_lo_que_no_esta_no_toca_nada(self):
        estado = añadir(EstadoPedido(), [HAMBURGUESA])
        nuevo, quitadas = quitar(estado, "pizza")

        assert quitadas == ()
        assert nuevo.total == estado.total

    def test_un_nombre_vacio_no_vacia_el_carrito(self):
        """Sin esto, un nombre en blanco casaria con todo."""
        estado = añadir(EstadoPedido(), [HAMBURGUESA, PERRO])
        nuevo, quitadas = quitar(estado, "")

        assert quitadas == ()
        assert nuevo.total == estado.total


class TestElParcheLlevaSiempreLasSieteClaves:
    """
    La razon de ser del modulo. Los escritores ya no eligen que claves tocar,
    asi que no pueden olvidarse de una -- que es lo que produjo los tres fallos.
    """

    CLAVES = {"cart", "pending_products", "pending_product",
              "awaiting_confirmation", "total"}

    @pytest.mark.parametrize("estado", [
        EstadoPedido(),
        proponer(EstadoPedido(), [HAMBURGUESA]),
        añadir(EstadoPedido(), [HAMBURGUESA, PERRO]),
        vaciar(proponer(EstadoPedido(), [HAMBURGUESA])),
        descartar(proponer(EstadoPedido(), [HAMBURGUESA])),
    ])
    def test_todas_presentes_en_cada_operacion(self, estado):
        assert self.CLAVES <= set(a_session_data(estado))

    def test_el_total_cuadra_con_las_lineas(self):
        datos = a_session_data(añadir(EstadoPedido(), [HAMBURGUESA, PERRO]))
        assert datos["total"] == 30.0
        assert sum(i["price"] * i["quantity"] for i in datos["cart"]) == datos["total"]

    def test_la_clave_antigua_se_apaga_siempre(self):
        """Quedan sesiones con pending_product; hay que apagarla, no ignorarla."""
        assert a_session_data(proponer(EstadoPedido(), [HAMBURGUESA]))["pending_product"] is None

    def test_ida_y_vuelta(self):
        original = añadir(proponer(EstadoPedido(), [SIN_CEBOLLA]), [PERRO])
        assert leer(a_session_data(original)) == original

    def test_las_modificaciones_sobreviven_al_guardado(self):
        datos = a_session_data(añadir(EstadoPedido(), [SIN_CEBOLLA]))
        assert datos["cart"][0]["modifications"] == ["sin cebolla"]


class TestNadieEscribeElEstadoPorSuCuenta:
    """
    El guardia. Sin el, la proxima rama que alguien escriba volvera a tocar
    session_data["cart"] a mano y a olvidarse de otra clave.
    """

    RAIZ = Path(__file__).resolve().parent.parent
    DUEÑO = RAIZ / "services" / "whatsapp" / "estado_pedido.py"
    ESCRITURA = re.compile(
        r"""session_data\s*\[\s*["'](cart|pending_products|pending_product|"""
        r"""awaiting_confirmation|total)["']\s*\]\s*="""
    )

    def test_solo_el_modulo_escribe_esas_claves(self):
        infractores = []
        for ruta in self.RAIZ.rglob("*.py"):
            if any(x in ruta.parts for x in ("venv", "tests", "__pycache__")):
                continue
            if ruta == self.DUEÑO:
                continue
            for numero, linea in enumerate(
                ruta.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
            ):
                if self.ESCRITURA.search(linea):
                    infractores.append(f"{ruta.relative_to(self.RAIZ)}:{numero} {linea.strip()[:60]}")

        assert not infractores, (
            "Estos sitios escriben el estado del pedido a mano. Usa las "
            "operaciones de services/whatsapp/estado_pedido.py:\n  "
            + "\n  ".join(infractores)
        )

    def test_el_detector_reconoce_una_infraccion(self):
        assert self.ESCRITURA.search('session_data["cart"] = cart')
        assert self.ESCRITURA.search("session_data['pending_products'] = x")

    def test_el_detector_no_marca_una_lectura(self):
        assert not self.ESCRITURA.search('cart = session_data.get("cart", [])')


class TestQuitarDelCarritoPorConversacion:
    """
    El cableado de la operacion que faltaba. Hasta hoy, un cliente que decia
    "quitame las papas" recibia "Funcion de remover productos en desarrollo" y
    su unica salida era cancelar el pedido entero y empezar de cero.
    """

    def _handler_con_carrito(self, carrito):
        from unittest.mock import AsyncMock, MagicMock

        from services.whatsapp.handlers.llm_handler import LLMHandler

        handler = LLMHandler(MagicMock())
        handler.update_session_state = AsyncMock()
        sesion = {"id": "s-1", "session_data": a_session_data(
            añadir(EstadoPedido(), carrito)
        )}
        return handler, sesion

    @pytest.mark.asyncio
    async def test_quita_lo_pedido_y_deja_el_resto(self):
        handler, sesion = self._handler_con_carrito([HAMBURGUESA, PERRO])

        respuesta = await handler._handle_remove_from_cart(
            [{"name": "perro caliente"}], "", sesion, [], "es"
        )

        _, _, datos = handler.update_session_state.await_args.args
        assert len(datos["cart"]) == 1
        assert datos["cart"][0]["name"] == "hamburguesa"
        assert datos["total"] == 10.0
        assert "perro caliente" in respuesta

    @pytest.mark.asyncio
    async def test_quitar_lo_ultimo_avisa_de_que_quedo_vacio(self):
        handler, sesion = self._handler_con_carrito([HAMBURGUESA])

        respuesta = await handler._handle_remove_from_cart(
            [{"name": "hamburguesa"}], "", sesion, [], "es"
        )

        assert "vac" in respuesta.lower()

    @pytest.mark.asyncio
    async def test_quitar_algo_que_no_esta_no_toca_el_carrito(self):
        handler, sesion = self._handler_con_carrito([HAMBURGUESA])

        respuesta = await handler._handle_remove_from_cart(
            [{"name": "pizza"}], "", sesion, [], "es"
        )

        handler.update_session_state.assert_not_awaited()
        assert "pizza" in respuesta

    @pytest.mark.asyncio
    async def test_con_el_carrito_vacio_lo_dice(self):
        from unittest.mock import AsyncMock, MagicMock

        from services.whatsapp.handlers.llm_handler import LLMHandler

        handler = LLMHandler(MagicMock())
        handler.update_session_state = AsyncMock()

        respuesta = await handler._handle_remove_from_cart(
            [{"name": "hamburguesa"}], "", {"id": "s-1", "session_data": {}}, [], "es"
        )

        assert respuesta
        handler.update_session_state.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ya_no_dice_que_esta_en_desarrollo(self):
        """Lo que veia el cliente hasta hoy."""
        handler, sesion = self._handler_con_carrito([HAMBURGUESA])

        respuesta = await handler._handle_remove_from_cart(
            [{"name": "hamburguesa"}], "", sesion, [], "es"
        )

        assert "desarrollo" not in respuesta.lower()
