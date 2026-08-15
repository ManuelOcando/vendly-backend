"""
"Una hamburguesa sin cebolla", sin LLM.

La cadena determinista no entendia modificaciones, y eso no fallaba: mentia.
"hamburguesa sin cebolla" casaba con "Hamburguesa" por contencion, entraba al
carrito pelada, el bot contestaba `✅ Hamburguesa` y a la cocina llegaba con
cebolla. Ni error, ni log, ni una linea fuera de sitio: solo el pedido
equivocado y un cliente que no vuelve.

Con el modelo en el plan gratuito -- 20 peticiones al dia -- esta es la ruta que
corre casi siempre, asi que el fallo no era un caso raro: era el caso normal.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.i18n import t
from services.whatsapp.handlers.customer import ProductOrderHandler, modificacion_suelta
from services.whatsapp.modificaciones import (
    parece_modificacion, posibles_cortes, preposicion,
)


CATALOGO = [
    {"id": "p-1", "name": "Hamburguesa", "price": 10.0, "description": ""},
    {"id": "p-2", "name": "Papas", "price": 4.5, "description": ""},
    {"id": "p-3", "name": "Café con leche", "price": 3.0, "description": ""},
]


def handler_con(catalogo=None):
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=catalogo if catalogo is not None else CATALOGO)
    )
    handler = ProductOrderHandler(db)
    handler.update_session_state = AsyncMock()
    return handler


async def pedir(handler, mensaje):
    """Devuelve el carrito guardado tras un mensaje."""
    await handler.handle({
        "tenant_id": "t-1", "phone": "+1", "message": mensaje, "language": "es",
        "session": {"id": "s-1", "current_state": "initial", "session_data": {}},
    })
    return handler.update_session_state.await_args.args[2]["cart"]


class TestLasLecturasPosibles:
    """Puro texto: donde puede acabar el nombre y empezar lo que se le cambia."""

    def test_de_la_mas_larga_a_la_mas_corta(self):
        assert posibles_cortes("cafes con leche sin azucar") == [
            ("cafes con leche sin azucar", []),
            ("cafes con leche", ["sin azucar"]),
            ("cafes", ["con leche", "sin azucar"]),
        ]

    def test_el_texto_entero_siempre_es_la_primera(self):
        """Asi el comportamiento anterior queda de primera opcion."""
        for texto in ("hamburguesa", "hamburguesa sin cebolla", "papas fritas"):
            assert posibles_cortes(texto)[0] == (texto, [])

    def test_varias_modificaciones_seguidas(self):
        assert posibles_cortes("hamburguesa sin cebolla sin mayonesa")[-1] == (
            "hamburguesa", ["sin cebolla", "sin mayonesa"]
        )

    def test_no_parte_dentro_de_una_palabra(self):
        """"bacon" lleva un "con" dentro, y "vino tinto" un "no"."""
        assert posibles_cortes("bacon") == [("bacon", [])]
        assert posibles_cortes("vino tinto") == [("vino tinto", [])]

    def test_una_modificacion_suelta_no_inventa_un_producto(self):
        assert posibles_cortes("sin cebolla") == [("sin cebolla", [])]

    def test_reconoce_los_tres_idiomas(self):
        assert parece_modificacion("sin cebolla")
        assert parece_modificacion("without onion")
        assert parece_modificacion("sem cebola")
        assert not parece_modificacion("hamburguesa")


class TestElCatalogoDecideDondeCortar:
    @pytest.mark.asyncio
    async def test_la_modificacion_llega_al_carrito(self):
        carrito = await pedir(handler_con(), "quiero una hamburguesa sin cebolla")

        assert len(carrito) == 1
        assert carrito[0]["name"] == "Hamburguesa"
        assert carrito[0]["modifications"] == ["sin cebolla"], (
            "se perdio por el camino, que es como llegaba con cebolla a la cocina"
        )

    @pytest.mark.asyncio
    async def test_un_producto_que_se_llama_con_algo_no_se_parte(self):
        """
        "Café con leche" es un producto, no un cafe modificado. La pasada
        exacta va primera justo para esto.
        """
        carrito = await pedir(handler_con(), "un café con leche")

        assert carrito[0]["name"] == "Café con leche"
        assert carrito[0]["modifications"] == []

    @pytest.mark.asyncio
    async def test_un_producto_que_se_llama_con_algo_admite_modificacion(self):
        carrito = await pedir(handler_con(), "un café con leche sin azúcar")

        assert carrito[0]["name"] == "Café con leche"
        assert carrito[0]["modifications"] == ["sin azúcar"]

    @pytest.mark.asyncio
    async def test_la_cantidad_y_la_modificacion_conviven(self):
        carrito = await pedir(handler_con(), "2 hamburguesas sin cebolla")

        assert carrito[0]["quantity"] == 2
        assert carrito[0]["modifications"] == ["sin cebolla"]

    @pytest.mark.asyncio
    async def test_dos_modificaciones_partidas_por_el_separador(self):
        """
        " y " es un separador de productos, asi que esto se parte en dos y el
        segundo trozo no existe en ningun catalogo. El cliente leia
        'No encontre "sin mayonesa"' y se quedaba sin la mayonesa quitada.
        """
        carrito = await pedir(
            handler_con(), "una hamburguesa sin cebolla y sin mayonesa"
        )

        assert len(carrito) == 1, "la modificacion se conto como otro producto"
        assert carrito[0]["modifications"] == ["sin cebolla", "sin mayonesa"]

    @pytest.mark.asyncio
    async def test_dos_productos_de_verdad_siguen_siendo_dos(self):
        carrito = await pedir(handler_con(), "una hamburguesa y unas papas")

        assert [i["name"] for i in carrito] == ["Hamburguesa", "Papas"]

    @pytest.mark.asyncio
    async def test_el_mismo_producto_con_y_sin_modificacion_son_dos_lineas(self):
        """En la cocina son dos platos distintos."""
        handler = handler_con()
        await pedir(handler, "una hamburguesa")
        guardado = handler.update_session_state.await_args.args[2]

        await handler.handle({
            "tenant_id": "t-1", "phone": "+1",
            "message": "otra hamburguesa sin cebolla", "language": "es",
            "session": {"id": "s-1", "current_state": "ordering", "session_data": guardado},
        })
        carrito = handler.update_session_state.await_args.args[2]["cart"]

        assert len(carrito) == 2
        assert [i["modifications"] for i in carrito] == [[], ["sin cebolla"]]

    @pytest.mark.asyncio
    async def test_lo_que_no_existe_sigue_diciendolo(self):
        handler = handler_con()
        respuesta = await handler.handle({
            "tenant_id": "t-1", "phone": "+1", "message": "sushi de trufa",
            "language": "es",
            "session": {"id": "s-1", "current_state": "initial", "session_data": {}},
        })

        assert "sushi de trufa" in respuesta
        handler.update_session_state.assert_not_awaited()


class TestCorregirLoYaPedido:
    """
    "La hamburguesa que sea sin salsa" con una hamburguesa ya pedida es
    corregirla, no pedir otra.

    ProductOrderHandler solo sabia añadir. Desde que entiende modificaciones,
    `_fusionar` separa las lineas por (id, modificaciones), asi que una
    correccion le parecia un producto distinto: dos hamburguesas en el pedido,
    dos platos en la cocina, y el cliente pagando la que no pidio. Salio al
    agotarse la cuota de Gemini, cuando esta cadena paso a contestar sola.
    """

    async def _con_una_hamburguesa(self):
        handler = handler_con()
        await pedir(handler, "una hamburguesa sin cebolla")
        return handler, handler.update_session_state.await_args.args[2]

    async def _seguir(self, handler, guardado, mensaje):
        await handler.handle({
            "tenant_id": "t-1", "phone": "+1", "message": mensaje, "language": "es",
            "session": {"id": "s-1", "current_state": "ordering", "session_data": guardado},
        })
        return handler.update_session_state.await_args.args[2]

    @pytest.mark.asyncio
    async def test_corregir_no_añade_una_linea(self):
        handler, guardado = await self._con_una_hamburguesa()

        carrito = (await self._seguir(
            handler, guardado, "la hamburguesa que sea sin salsa"
        ))["cart"]

        assert len(carrito) == 1, "corregir el pedido añadio un producto"
        assert carrito[0]["modifications"] == ["sin cebolla", "sin salsa"]
        assert carrito[0]["quantity"] == 1

    @pytest.mark.asyncio
    async def test_sin_palabras_de_correccion_sigue_añadiendo(self):
        """
        La decision tomada, fijada para que no se mueva sin querer: quien
        escribe "hamburguesa sin salsa" a secas puede querer una segunda.
        Equivocarse añadiendo se ve en el resumen antes de confirmar.
        """
        handler, guardado = await self._con_una_hamburguesa()

        carrito = (await self._seguir(handler, guardado, "hamburguesa sin salsa"))["cart"]

        assert len(carrito) == 2

    @pytest.mark.asyncio
    async def test_corregir_sin_nombrar_el_producto(self):
        """Con una sola linea no hay nada que adivinar."""
        handler, guardado = await self._con_una_hamburguesa()

        carrito = (await self._seguir(handler, guardado, "que sea sin salsa"))["cart"]

        assert len(carrito) == 1
        assert carrito[0]["modifications"] == ["sin cebolla", "sin salsa"]

    @pytest.mark.asyncio
    async def test_corregir_sin_nombrar_con_dos_lineas_pregunta(self):
        handler, guardado = await self._con_una_hamburguesa()
        guardado = await self._seguir(handler, guardado, "unas papas")

        respuesta = await handler.handle({
            "tenant_id": "t-1", "phone": "+1", "message": "que sea sin sal",
            "language": "es",
            "session": {"id": "s-1", "current_state": "ordering", "session_data": guardado},
        })

        assert respuesta == t("llm.what_to_modify", "es")

    @pytest.mark.asyncio
    async def test_corregir_algo_que_no_esta_pedido_lo_pide(self):
        handler, guardado = await self._con_una_hamburguesa()

        carrito = (await self._seguir(
            handler, guardado, "las papas que sean sin sal"
        ))["cart"]

        assert [i["name"] for i in carrito] == ["Hamburguesa", "Papas"]
        assert carrito[1]["modifications"] == ["sin sal"]

    @pytest.mark.asyncio
    async def test_corregir_lo_que_solo_estaba_propuesto(self):
        """
        Y sin dar por aceptada la propuesta: `añadir(estado, [])` funde los
        pendientes en el carrito, asi que una correccion pura no puede pasar
        por ahi.
        """
        from services.whatsapp import estado_pedido

        propuesto = estado_pedido.a_session_data(
            estado_pedido.proponer(estado_pedido.EstadoPedido(), [
                {"product_id": "p-1", "name": "Hamburguesa", "price": 10.0, "quantity": 1},
            ])
        )
        handler = handler_con()
        guardado = await self._seguir(
            handler, propuesto, "la hamburguesa que sea sin salsa"
        )

        assert guardado["cart"] == [], "se dio por aceptada una propuesta sin confirmar"
        assert len(guardado["pending_products"]) == 1
        assert guardado["pending_products"][0]["modifications"] == ["sin salsa"]


class TestModificacionesSinPreposicion:
    """
    "Ponle queso a la hamburguesa".

    `posibles_cortes` localiza la modificacion buscando un `sin `/`con ` que
    diga donde empieza. Aqui no hay ninguno: "queso" va suelto, asi que se
    casaba "Hamburguesa" por contencion sobre la frase entera y se añadia una
    hamburguesa pelada. El queso desaparecia sin un solo error.
    """

    def test_el_verbo_dice_que_hacer_con_lo_que_sobra(self):
        assert preposicion("ponle queso") == "con "
        assert preposicion("quitale la cebolla") == "sin "
        assert preposicion("agregale tocineta") == "con "
        assert preposicion("remove the onion") == "sin "
        # Una correccion neutra no inventa preposicion: "grande" no es ni con
        # ni sin nada.
        assert preposicion("que sea grande") == ""

    @pytest.mark.parametrize("mensaje,esperado", [
        ("ponle queso a la hamburguesa", ["con queso"]),
        ("quitale la cebolla a la hamburguesa", ["sin cebolla"]),
        ("la hamburguesa que sea grande", ["grande"]),
        # Sin nada que corregir aparte del propio producto.
        ("una hamburguesa", []),
    ])
    def test_lo_que_sobra_del_mensaje(self, mensaje, esperado):
        assert modificacion_suelta(mensaje, "Hamburguesa") == esperado

    @pytest.mark.asyncio
    async def test_ponle_queso_no_añade_una_hamburguesa(self):
        handler = handler_con()
        await pedir(handler, "una hamburguesa sin cebolla")
        guardado = handler.update_session_state.await_args.args[2]

        await handler.handle({
            "tenant_id": "t-1", "phone": "+1",
            "message": "ponle queso a la hamburguesa", "language": "es",
            "session": {"id": "s-1", "current_state": "ordering", "session_data": guardado},
        })
        carrito = handler.update_session_state.await_args.args[2]["cart"]

        assert len(carrito) == 1, "puso el queso en una hamburguesa nueva"
        assert carrito[0]["modifications"] == ["sin cebolla", "con queso"]

    @pytest.mark.asyncio
    async def test_quitarle_algo_tampoco_duplica(self):
        handler = handler_con()
        await pedir(handler, "una hamburguesa")
        guardado = handler.update_session_state.await_args.args[2]

        await handler.handle({
            "tenant_id": "t-1", "phone": "+1",
            "message": "quitale la cebolla a la hamburguesa", "language": "es",
            "session": {"id": "s-1", "current_state": "ordering", "session_data": guardado},
        })
        carrito = handler.update_session_state.await_args.args[2]["cart"]

        assert len(carrito) == 1
        assert carrito[0]["modifications"] == ["sin cebolla"]

    @pytest.mark.asyncio
    async def test_sin_nombrar_el_producto_y_con_dos_lineas_pregunta(self):
        handler = handler_con()
        await pedir(handler, "una hamburguesa")
        guardado = handler.update_session_state.await_args.args[2]
        await handler.handle({
            "tenant_id": "t-1", "phone": "+1", "message": "unas papas", "language": "es",
            "session": {"id": "s-1", "current_state": "ordering", "session_data": guardado},
        })
        guardado = handler.update_session_state.await_args.args[2]

        respuesta = await handler.handle({
            "tenant_id": "t-1", "phone": "+1", "message": "ponle queso", "language": "es",
            "session": {"id": "s-1", "current_state": "ordering", "session_data": guardado},
        })

        assert respuesta == t("llm.what_to_modify", "es")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mensaje,esperado", [
        # El verbo no puede colarse dentro de la modificacion. "agregale" no
        # esta en las claves de `correction`, solo en VERBOS_AÑADIR, y salia
        # "con agregale tocineta".
        ("agregale tocineta", ["sin cebolla", "con tocineta"]),
        ("quitame la mayonesa", ["sin cebolla", "sin mayonesa"]),
        ("add bacon", ["sin cebolla", "con bacon"]),
    ])
    async def test_el_verbo_no_acaba_dentro_de_la_modificacion(self, mensaje, esperado):
        handler = handler_con()
        await pedir(handler, "una hamburguesa sin cebolla")
        guardado = handler.update_session_state.await_args.args[2]

        await handler.handle({
            "tenant_id": "t-1", "phone": "+1", "message": mensaje, "language": "es",
            "session": {"id": "s-1", "current_state": "ordering", "session_data": guardado},
        })
        carrito = handler.update_session_state.await_args.args[2]["cart"]

        assert len(carrito) == 1
        assert carrito[0]["modifications"] == esperado

    @pytest.mark.asyncio
    async def test_la_correccion_se_lee_del_fragmento_no_del_mensaje(self):
        """
        "ponle queso y unas papas" se parte en dos por el separador " y ".
        Leyendo el mensaje entero, la modificacion salia "con queso y papas" --
        con las papas dentro de la hamburguesa y ademas pedidas aparte.
        """
        handler = handler_con()
        await pedir(handler, "una hamburguesa")
        guardado = handler.update_session_state.await_args.args[2]

        await handler.handle({
            "tenant_id": "t-1", "phone": "+1",
            "message": "ponle queso y unas papas", "language": "es",
            "session": {"id": "s-1", "current_state": "ordering", "session_data": guardado},
        })
        carrito = handler.update_session_state.await_args.args[2]["cart"]

        assert [i["name"] for i in carrito] == ["Hamburguesa", "Papas"]
        assert carrito[0]["modifications"] == ["con queso"]

    @pytest.mark.asyncio
    async def test_un_producto_que_empieza_por_un_verbo_no_es_una_correccion(self):
        """
        "Tira de asado" es un producto. Un falso positivo aqui convierte un
        pedido normal en una correccion, que es mucho peor que no detectarla:
        por eso los verbos son solo formas inequivocas, casi todas con el
        pronombre pegado.
        """
        catalogo = CATALOGO + [
            {"id": "p-4", "name": "Tira de asado", "price": 18.0, "description": ""},
        ]
        handler = handler_con(catalogo)
        await pedir(handler, "una hamburguesa")
        guardado = handler.update_session_state.await_args.args[2]

        await handler.handle({
            "tenant_id": "t-1", "phone": "+1", "message": "una tira de asado",
            "language": "es",
            "session": {"id": "s-1", "current_state": "ordering", "session_data": guardado},
        })
        carrito = handler.update_session_state.await_args.args[2]["cart"]

        assert [i["name"] for i in carrito] == ["Hamburguesa", "Tira de asado"]
        assert all(i["modifications"] == [] for i in carrito)

    @pytest.mark.asyncio
    async def test_un_pedido_normal_no_gana_modificaciones(self):
        """
        Esto solo actua con lenguaje de correccion. Sin el guardia, cualquier
        palabra de mas en un pedido normal acabaria pegada al producto.
        """
        handler = handler_con()
        carrito = await pedir(handler, "quiero una hamburguesa por favor")

        assert carrito[0]["modifications"] == []


class TestLoQueVeElCliente:
    @pytest.mark.asyncio
    async def test_el_acuse_enseña_la_modificacion(self):
        """
        Confirmar "Hamburguesa" cuando se pidio sin cebolla es pedirle al
        cliente que de por bueno algo que no puede revisar.
        """
        handler = handler_con()
        respuesta = await handler.handle({
            "tenant_id": "t-1", "phone": "+1",
            "message": "una hamburguesa sin cebolla", "language": "es",
            "session": {"id": "s-1", "current_state": "initial", "session_data": {}},
        })

        assert "sin cebolla" in respuesta
        assert "✅ Hamburguesa (sin cebolla)" in respuesta
