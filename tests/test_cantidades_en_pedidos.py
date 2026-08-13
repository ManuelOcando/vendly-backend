"""
Cantidades al pedir por conversacion.

Cada producto nombrado entraba al carrito con cantidad 1: quien pedia dos
hamburguesas recibia una, y se enteraba al llegar el pedido. Salio probando el
recorrido conversacional entero -- el test pedia dos y llegaba una.

Los casos de "lo que NO es una cantidad" son los que importan a largo plazo: un
"pizza 4 quesos" convertido en cuatro quesos es peor que no leer cantidades.
"""
import pytest

from services.whatsapp.handlers.customer import (
    CANTIDAD_MAXIMA,
    extraer_cantidad,
)


class TestFormasDeEscribirla:
    @pytest.mark.parametrize("texto,cantidad,nombre", [
        ("2 hamburguesas", 2, "hamburguesas"),
        ("3 perros calientes", 3, "perros calientes"),
        ("2x hamburguesa", 2, "hamburguesa"),
        ("hamburguesa x2", 2, "hamburguesa"),
        ("hamburguesa X3", 3, "hamburguesa"),
        ("hamburguesa *2", 2, "hamburguesa"),
    ])
    def test_con_cifras(self, texto, cantidad, nombre):
        assert extraer_cantidad(texto) == (cantidad, nombre)

    @pytest.mark.parametrize("texto,cantidad,nombre", [
        ("dos hamburguesas", 2, "hamburguesas"),
        ("tres empanadas", 3, "empanadas"),
        ("una hamburguesa", 1, "hamburguesa"),
        ("diez cervezas", 10, "cervezas"),
        ("two burgers", 2, "burgers"),
        ("dois hamburgueres", 2, "hamburgueres"),
    ])
    def test_con_letras_en_los_tres_idiomas(self, texto, cantidad, nombre):
        assert extraer_cantidad(texto) == (cantidad, nombre)

    @pytest.mark.parametrize("texto", [
        "quiero 2 hamburguesas",
        "dame 2 hamburguesas",
        "me quiero 2 hamburguesas",
        "ponme 2 hamburguesas",
        "necesito 2 hamburguesas",
        "i want 2 hamburguesas",
        "quero 2 hamburguesas",
    ])
    def test_el_verbo_de_delante_no_estorba(self, texto):
        """_split_products deja el verbo pegado al primer producto."""
        assert extraer_cantidad(texto) == (2, "hamburguesas")


class TestLoQueNoEsUnaCantidad:
    """
    La regla es estrecha a proposito: el numero va al principio, o detras de una
    x. Buscarlo en cualquier posicion seria mas permisivo y mucho peor.
    """

    @pytest.mark.parametrize("texto", [
        "pizza 4 quesos",
        "refresco 2 litros",
        "combo 3 pisos",
        "salsa 7 especias",
    ])
    def test_un_numero_dentro_del_nombre_no_es_cantidad(self, texto):
        assert extraer_cantidad(texto) == (1, texto)

    @pytest.mark.parametrize("texto", ["hamburguesa", "perro caliente", ""])
    def test_sin_numero_es_una_unidad(self, texto):
        assert extraer_cantidad(texto) == (1, texto)

    def test_el_nombre_devuelto_no_lleva_el_numero(self):
        """Si lo llevara, no casaria con el nombre del catalogo."""
        _, nombre = extraer_cantidad("2 hamburguesas")
        assert "2" not in nombre


class TestTope:
    def test_un_numero_absurdo_se_acota(self):
        """
        Un modelo alucinando ya invento un pedido de 17 hamburguesas. Con tres
        cifras el destrozo seria mayor.
        """
        assert extraer_cantidad("500 hamburguesas") == (CANTIDAD_MAXIMA, "hamburguesas")

    def test_cero_es_un_error_de_tecleo_no_una_peticion(self):
        assert extraer_cantidad("0 hamburguesas") == (1, "hamburguesas")


class TestEnElCarrito:
    """Que la cantidad llegue de verdad al carrito, no solo se lea bien."""

    @pytest.mark.asyncio
    async def test_pedir_dos_pone_dos(self):
        from unittest.mock import AsyncMock, MagicMock

        from services.whatsapp.handlers.customer import ProductOrderHandler

        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"id": "p-1", "name": "Hamburguesa", "price": 10.0, "description": ""}]
        )

        handler = ProductOrderHandler(db)
        handler.update_session_state = AsyncMock()

        respuesta = await handler.handle({
            "tenant_id": "t-1", "phone": "+1", "message": "quiero 2 hamburguesas",
            "language": "es",
            "session": {"id": "s-1", "current_state": "initial", "session_data": {}},
        })

        _, _, datos = handler.update_session_state.await_args.args
        carrito = datos["cart"]
        assert len(carrito) == 1
        assert carrito[0]["quantity"] == 2, "pidio dos y se guardo otra cantidad"
        assert datos["total"] == 20.0
        assert "20.00" in respuesta
