"""
"Sin cebolla" tiene que llegar hasta la cocina.

El bot entendia las modificaciones desde el principio: las detectaba, las
mostraba en la propuesta y las guardaba en el carrito de la sesion. Y ahi
morian. order_items no tenia columna para ellas, el resumen del carrito no las
enseñaba, y el aviso al vendedor decia "1x hamburguesa".

En una conversacion real del 13/08/2026 el cliente pidio una hamburguesa sin
cebolla y sin salsa de tomate, el bot se lo confirmo palabra por palabra, y lo
que habria llegado a la plancha era una hamburguesa normal. Un pedido devuelto,
un cliente perdido, y ni una linea en los logs que lo explique.
"""
import pytest

from services.whatsapp.handlers.customer import (
    crear_pedido,
    linea_de_carrito,
    normalizar_items,
)


def item_de_sesion(nombre="hamburguesa", cantidad=1, modificaciones=None):
    return {
        "product_id": "p-1", "name": nombre, "price": 10.0,
        "quantity": cantidad, "modifications": modificaciones or [],
    }


class TestSobrevivenALaNormalizacion:
    def test_se_conservan(self):
        [item] = normalizar_items([item_de_sesion(modificaciones=["sin cebolla"])])
        assert item["modifications"] == ["sin cebolla"]

    def test_varias_se_conservan_en_orden(self):
        [item] = normalizar_items(
            [item_de_sesion(modificaciones=["sin cebolla", "sin salsa de tomate"])]
        )
        assert item["modifications"] == ["sin cebolla", "sin salsa de tomate"]

    def test_sin_modificaciones_queda_una_lista_vacia(self):
        """Nunca None: la columna es NOT NULL con default '[]'."""
        [item] = normalizar_items([item_de_sesion()])
        assert item["modifications"] == []

    def test_el_carrito_de_la_tienda_web_tambien(self):
        """Ese usa item_id en vez de product_id."""
        [item] = normalizar_items([{
            "item_id": "p-1", "name": "hamburguesa", "price": 10.0,
            "quantity": 1, "modifications": ["sin cebolla"],
        }])
        assert item["modifications"] == ["sin cebolla"]

    def test_no_comparte_la_lista_con_el_carrito_de_origen(self):
        """Compartirla dejaria que un cambio en el pedido tocase la sesion."""
        origen = item_de_sesion(modificaciones=["sin cebolla"])
        [item] = normalizar_items([origen])
        item["modifications"].append("sin queso")
        assert origen["modifications"] == ["sin cebolla"]


class TestLleganAlPedido:
    @pytest.mark.asyncio
    async def test_se_escriben_en_order_items(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        escrito = {}

        db = MagicMock()

        def tabla(nombre):
            q = MagicMock()
            if nombre == "orders":
                q.insert.return_value.execute.return_value = MagicMock(
                    data=[{"id": "order-1"}]
                )
            elif nombre == "order_items":
                def insert(filas):
                    escrito["order_items"] = filas
                    return MagicMock(execute=MagicMock())
                q.insert.side_effect = insert
            else:
                q.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
            return q

        db.table.side_effect = tabla

        with patch("services.whatsapp.handlers.customer.CustomerProfileService"), \
             patch("services.whatsapp.handlers.customer._avisar_al_vendedor", AsyncMock()):
            await crear_pedido(db, "t-1", "+1", [
                item_de_sesion(modificaciones=["sin cebolla", "sin salsa de tomate"]),
            ], "es")

        assert escrito["order_items"][0]["modifications"] == [
            "sin cebolla", "sin salsa de tomate"
        ]


class TestLasVeElVendedorYElCliente:
    def test_el_resumen_del_carrito_las_enseña(self):
        linea = linea_de_carrito(item_de_sesion(modificaciones=["sin cebolla"]))
        assert "sin cebolla" in linea
        assert linea == "• hamburguesa (sin cebolla) x1 - $10.00"

    def test_sin_modificaciones_no_deja_parentesis_vacios(self):
        assert linea_de_carrito(item_de_sesion()) == "• hamburguesa x1 - $10.00"

    @pytest.mark.asyncio
    async def test_el_aviso_al_vendedor_las_lleva(self):
        from unittest.mock import MagicMock, patch

        from services.whatsapp.handlers.customer import _avisar_al_vendedor

        enviados = []
        servicio = MagicMock()
        servicio.return_value.send_message.side_effect = lambda tel, msg: enviados.append(msg)

        with patch("services.whatsapp.handlers.customer.MetaWhatsAppService", servicio), \
             patch("services.whatsapp.handlers.customer.fetch_config", return_value={
                 "seller_phone": "+58412", "phone_number_id": "p", "access_token": "t",
             }):
            await _avisar_al_vendedor(
                MagicMock(), "t-1", "+1", {"id": "order-1234abcd"},
                normalizar_items([item_de_sesion(cantidad=2, modificaciones=["sin cebolla"])]),
                20.0,
            )

        assert "sin cebolla" in enviados[0], "el vendedor no ve que va sin cebolla"
        assert "2x hamburguesa" in enviados[0]
