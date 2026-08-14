"""
Añadir productos no borra los que ya estaban pendientes.

Paso en una conversacion real. El cliente pidio cinco productos por $50, el bot
se los propuso bien, y al decir "ponme otra hamburguesa sin cebolla" la propuesta
paso a ser **solo esa hamburguesa, $10**. Los cinco anteriores desaparecieron sin
aviso, y eso fue lo que acabo confirmando: un carrito de $10 en vez de $60.

La causa era una asignacion donde tenia que haber una fusion:
`session_data["pending_products"] = pending_products`.
"""
import pytest

from services.whatsapp.handlers.llm_handler import (
    _linea_de_producto,
    fusionar_pendientes,
)


def producto(nombre, cantidad=1, modificaciones=None, id_=None, precio=10.0):
    return {
        "product_id": id_ or nombre,
        "name": nombre,
        "price": precio,
        "quantity": cantidad,
        "modifications": modificaciones or [],
    }


class TestSeAcumulan:
    def test_lo_nuevo_se_suma_a_lo_que_habia(self):
        anteriores = [producto("hamburguesa"), producto("perro caliente", 2)]
        nuevos = [producto("papas")]

        resultado = fusionar_pendientes(anteriores, nuevos)

        assert [p["name"] for p in resultado] == ["hamburguesa", "perro caliente", "papas"]

    def test_sin_nada_previo_devuelve_lo_nuevo(self):
        assert fusionar_pendientes(None, [producto("hamburguesa")])[0]["name"] == "hamburguesa"
        assert fusionar_pendientes([], [producto("hamburguesa")])[0]["name"] == "hamburguesa"

    def test_no_muta_la_lista_anterior(self):
        """La lista vive en session_data; modificarla en sitio esconde errores."""
        anteriores = [producto("hamburguesa")]
        fusionar_pendientes(anteriores, [producto("papas")])
        assert len(anteriores) == 1


class TestCuandoSeFundenDosLineas:
    def test_el_mismo_producto_sin_modificaciones_suma_cantidad(self):
        resultado = fusionar_pendientes(
            [producto("hamburguesa", 2)], [producto("hamburguesa", 1)]
        )
        assert len(resultado) == 1
        assert resultado[0]["quantity"] == 3

    def test_las_mismas_modificaciones_tambien_suman(self):
        resultado = fusionar_pendientes(
            [producto("hamburguesa", 1, ["sin cebolla"])],
            [producto("hamburguesa", 2, ["sin cebolla"])],
        )
        assert len(resultado) == 1
        assert resultado[0]["quantity"] == 3

    def test_modificaciones_distintas_son_lineas_distintas(self):
        """
        "hamburguesa" y "hamburguesa sin cebolla" son cosas distintas en la
        cocina. Fundirlas mandaria el pedido equivocado.
        """
        resultado = fusionar_pendientes(
            [producto("hamburguesa", 1, ["sin cebolla"])],
            [producto("hamburguesa", 1)],
        )
        assert len(resultado) == 2
        assert [p["quantity"] for p in resultado] == [1, 1]


class TestLaConversacionQueLoDestapo:
    """Los mensajes exactos de la conversacion del 13/08/2026, 21:46-21:48."""

    def test_el_pedido_no_encoge_al_añadir(self):
        primero = [
            producto("hamburguesa", 1, ["sin cebolla", "sin salsa de tomate"]),
            producto("hamburguesa", 1),
            producto("perro caliente", 1, ["sin salsa"], id_="perro"),
            producto("perro caliente", 2, ["con todo"], id_="perro"),
        ]
        assert sum(p["price"] * p["quantity"] for p in primero) == 50.0

        # "Pone otra hamburguesa sin cebolla pero con todo lo demas"
        resultado = fusionar_pendientes(
            primero, [producto("hamburguesa", 1, ["sin cebolla"])]
        )

        total = sum(p["price"] * p["quantity"] for p in resultado)
        assert total == 60.0, f"el pedido encogio de $50 a ${total:.2f}"
        assert len(resultado) == 5


class TestLaLineaQueVeElCliente:
    def test_lleva_nombre_modificaciones_cantidad_y_subtotal(self):
        linea = _linea_de_producto(producto("hamburguesa", 2, ["sin cebolla"]))
        assert linea == "• hamburguesa (sin cebolla) x2 - $20.00"

    def test_sin_modificaciones_no_pone_parentesis_vacios(self):
        assert _linea_de_producto(producto("hamburguesa")) == "• hamburguesa x1 - $10.00"


class TestCancelarLimpiaLasDosClaves:
    """
    _handle_cancel limpiaba pending_product -- la clave antigua, en singular --
    y dejaba pending_products, que es la que se usa.

    Inofensivo mientras nadie mirara los pendientes fuera de la confirmacion.
    Dejo de serlo el 13/08/2026, cuando _handle_add_to_cart empezo a volcar lo
    pendiente al carrito para no perderlo: a partir de ahi, cancelar y pedir
    cualquier otra cosa resucitaba el pedido cancelado.
    """

    @pytest.mark.asyncio
    async def test_cancelar_no_deja_productos_pendientes(self):
        from unittest.mock import AsyncMock, MagicMock

        from services.whatsapp.handlers.llm_handler import LLMHandler

        handler = LLMHandler(MagicMock())
        handler.update_session_state = AsyncMock()

        sesion = {"id": "s-1", "session_data": {
            "cart": [producto("hamburguesa")],
            "pending_products": [producto("perro caliente", 4)],
            "awaiting_confirmation": True,
        }}

        await handler._handle_cancel("", sesion, "es")

        _, _, datos = handler.update_session_state.await_args.args
        assert datos["cart"] == []
        assert not datos["pending_products"], "el pedido cancelado sigue pendiente"
        assert not datos["pending_product"]
        assert datos["awaiting_confirmation"] is False
