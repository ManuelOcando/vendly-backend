"""
La cadena determinista tiene que poder llevar una conversacion hasta el final.

No es un plan B. El plan gratuito de Gemini son 20 peticiones al DIA, asi que
esta cadena es el bot la mayor parte del tiempo. Fallaba justo en los dos
momentos que importan -- cerrar y cancelar -- y de una forma que no deja rastro
en los logs: el cliente lee un mensaje que parece razonable y su pedido no
existe.

Los recorridos completos estan en test_end_to_end_journey.py. Aqui se fijan los
contratos que no se ven desde fuera: que ningun handler escriba un estado que
nadie sepa leer, y quien reclama cada palabra.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.i18n import t
from services.whatsapp import estado_pedido
from services.whatsapp.handlers.customer import (
    CancelarPedidoHandler,
    CierreDePedidoHandler,
    WelcomeHandler,
    CartConfirmationHandler,
    ConfirmationHandler,
)
from services.whatsapp.handlers.llm_handler import LLMHandler


CARRITO = [{"product_id": "p-1", "name": "Hamburguesa", "price": 10.0, "quantity": 2}]


def _datos(mensaje, session_data=None, estado="ordering"):
    return {
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "phone": "584123456789",
        "message": mensaje,
        "language": "es",
        "session": {
            "id": "sess-1",
            "current_state": estado,
            "session_data": session_data if session_data is not None else {"cart": CARRITO},
        },
    }


class TestNingunEstadoQueNadieLea:
    """
    El fallo mas caro de este archivo, porque no se ve.

    `_handle_confirm_order` escribia el estado "confirming". No lo leia nadie:
    CartConfirmationHandler -- el unico sitio del backend que inserta en
    `orders` -- acepta `viewing_cart` u `ordering`. El cliente decia "confirmar
    mi pedido", el bot le enseñaba el resumen y le pedia un "si", y ese "si"
    caia en el hueco: al modelo suelto, o al menu generico con el LLM caido.

    La prueba ata los dos lados a proposito. Comprobar solo que se escribe
    "ordering" seria fijar una cadena de texto; lo que hay que garantizar es
    que quien cierra el pedido reconozca lo que dejo escrito quien lo preparo.
    """

    @pytest.mark.asyncio
    async def test_lo_que_escribe_confirmar_lo_entiende_quien_cierra(self):
        llm = LLMHandler(MagicMock())
        llm.update_session_state = AsyncMock()

        sesion = {"id": "sess-1", "current_state": "ordering", "session_data": {"cart": CARRITO}}
        await llm._handle_confirm_order("resumen", sesion, CARRITO, "es")

        llm.update_session_state.assert_awaited_once()
        estado_escrito = llm.update_session_state.await_args.args[1]

        cierre = CartConfirmationHandler(MagicMock())
        assert await cierre.can_handle(
            _datos("si", estado=estado_escrito)
        ), f"nadie sabe cerrar un pedido en el estado {estado_escrito!r}"

    @pytest.mark.asyncio
    async def test_lo_que_escribe_proponer_tampoco_es_un_callejon(self):
        """
        La otra rama del LLM escribia "awaiting_confirmation" como estado --
        el nombre de una clave de session_data, no de un estado. Con solo
        pendientes es ConfirmationHandler quien reclama el "si", pero en cuanto
        hay carrito el pedido tiene que poder cerrarse igual.
        """
        llm = LLMHandler(MagicMock())
        llm.update_session_state = AsyncMock()
        llm._find_product_in_db = AsyncMock(
            return_value={"id": "p-2", "name": "Papas", "price": 4.5}
        )

        estado = estado_pedido.añadir(estado_pedido.EstadoPedido(), CARRITO)
        sesion = {
            "id": "sess-1",
            "current_state": "ordering",
            "session_data": estado_pedido.a_session_data(estado),
        }
        await llm._handle_needs_confirmation(
            [{"name": "Papas", "quantity": 1}],
            "", sesion, "tenant", "584123456789", "es",
        )

        estado_escrito = llm.update_session_state.await_args.args[1]
        datos = _datos("si", session_data=sesion["session_data"], estado=estado_escrito)

        pendientes = ConfirmationHandler(MagicMock())
        cierre = CartConfirmationHandler(MagicMock())
        assert await pendientes.can_handle(datos) or await cierre.can_handle(datos), (
            f"un 'si' se queda sin dueño en el estado {estado_escrito!r}"
        )


    @pytest.mark.asyncio
    async def test_el_resumen_que_se_confirma_es_el_pedido_que_se_crea(self):
        """
        `_handle_confirm_order` enseñaba un resumen con lo pendiente incluido,
        pero el "si" siguiente crea el pedido desde session_data["cart"], que no
        lo lleva. El cliente confirmaba un resumen y recibia otro.

        La prueba ata las dos puntas: lo que dice el resumen tiene que ser lo
        que queda guardado para que lo lea quien inserta en `orders`.
        """
        llm = LLMHandler(MagicMock())
        llm.update_session_state = AsyncMock()

        estado = estado_pedido.proponer(estado_pedido.EstadoPedido(), CARRITO)
        sesion = {
            "id": "sess-1",
            "current_state": "ordering",
            "session_data": estado_pedido.a_session_data(estado),
        }
        resumen = await llm._handle_confirm_order("", sesion, [], "es")

        guardado = llm.update_session_state.await_args.args[2]
        assert guardado["cart"], "el resumen enseña un pedido que no queda guardado"
        assert not guardado["pending_products"]
        for item in guardado["cart"]:
            assert item["name"] in resumen

    @pytest.mark.asyncio
    async def test_lo_que_escribe_modificar_tampoco_es_un_callejon(self):
        """
        El tercero, y el mas caro: "la hamburguesa sin salsa" dejaba la
        conversacion en "cart_review". Corregir el pedido es lo que mas hace
        la gente pidiendo comida, y despues de corregirlo el "si" no cerraba
        nada. Ninguna prueba tocaba esta rama, que es como sobrevivio.
        """
        llm = LLMHandler(MagicMock())
        llm.update_session_state = AsyncMock()

        sesion = {
            "id": "sess-1",
            "current_state": "ordering",
            "session_data": estado_pedido.a_session_data(
                estado_pedido.añadir(estado_pedido.EstadoPedido(), CARRITO)
            ),
        }
        respuesta = await llm._handle_modify_cart_item(
            [{"name": "Hamburguesa", "modifications": ["sin salsa"]}],
            "", sesion, "tenant", "584123456789", "es",
        )

        assert "sin salsa" in respuesta

        estado_escrito = llm.update_session_state.await_args_list[0].args[1]
        guardado = llm.update_session_state.await_args_list[0].args[2]

        cierre = CartConfirmationHandler(MagicMock())
        assert await cierre.can_handle(
            _datos("si", session_data=guardado, estado=estado_escrito)
        ), f"no se puede cerrar un pedido corregido en el estado {estado_escrito!r}"

        # Y la correccion llega hasta la cocina, que es para lo que se pidio.
        assert guardado["cart"][0]["modifications"] == ["sin salsa"]


class TestCancelarDistingueElProductoDelPedido:
    """
    "Cancela las papas" no es "cancela el pedido".

    Esto estaba en manos del modelo, y probandolo de verdad la misma frase dio
    dos resultados en dos ejecuciones: una borro el pedido entero -- la
    hamburguesa que el cliente queria incluida -- y la otra contesto "he quitado
    las Papas" sin tocar el carrito. Las dos se lo confirmaron al cliente.
    """

    def _sesion(self, lineas=None, pendientes=None):
        estado = estado_pedido.añadir(
            estado_pedido.EstadoPedido(),
            lineas if lineas is not None else [
                {"product_id": "p-1", "name": "Hamburguesa", "price": 10.0, "quantity": 1},
                {"product_id": "p-2", "name": "Papas", "price": 4.5, "quantity": 1},
            ],
        )
        if pendientes:
            estado = estado_pedido.proponer(estado, pendientes)
        return estado_pedido.a_session_data(estado)

    @pytest.mark.asyncio
    async def test_nombrar_un_producto_quita_solo_ese(self):
        handler = CancelarPedidoHandler(MagicMock())
        handler.update_session_state = AsyncMock()

        respuesta = await handler.handle(_datos("cancela las papas", self._sesion()))

        guardado = handler.update_session_state.await_args.args[2]
        assert [i["name"] for i in guardado["cart"]] == ["Hamburguesa"], (
            "se llevo por delante lo que el cliente no nombro"
        )
        assert "Papas" in respuesta

    @pytest.mark.asyncio
    async def test_no_nombrar_nada_cancela_el_pedido(self):
        handler = CancelarPedidoHandler(MagicMock())
        handler.update_session_state = AsyncMock()

        respuesta = await handler.handle(_datos("cancelar mi pedido", self._sesion()))

        estado, guardado = handler.update_session_state.await_args.args[1:3]
        assert guardado["cart"] == []
        assert estado == "initial"
        assert respuesta == t("order.cancelled", "es")

    @pytest.mark.asyncio
    async def test_nombrar_algo_que_no_tiene_no_borra_nada(self):
        """
        Vaciar aqui seria borrarle el pedido a quien preguntaba por otra cosa.
        """
        handler = CancelarPedidoHandler(MagicMock())
        handler.update_session_state = AsyncMock()

        respuesta = await handler.handle(_datos("cancela la pizza", self._sesion()))

        handler.update_session_state.assert_not_awaited()
        assert "pizza" in respuesta

    @pytest.mark.asyncio
    async def test_tambien_cancela_lo_que_solo_estaba_propuesto(self):
        """Para el cliente no hay dos montones: es todo "lo que llevo"."""
        handler = CancelarPedidoHandler(MagicMock())
        handler.update_session_state = AsyncMock()

        sesion = self._sesion(
            lineas=[{"product_id": "p-1", "name": "Hamburguesa", "price": 10.0, "quantity": 1}],
            pendientes=[{"product_id": "p-2", "name": "Papas", "price": 4.5, "quantity": 1}],
        )
        await handler.handle(_datos("cancela las papas", sesion))

        guardado = handler.update_session_state.await_args.args[2]
        assert not guardado["pending_products"]
        assert [i["name"] for i in guardado["cart"]] == ["Hamburguesa"]

    @pytest.mark.asyncio
    async def test_el_modelo_ya_no_ve_estos_mensajes(self):
        """
        Con `cancel_order` entre las intenciones deterministas, LLMHandler cede
        antes de llamar. Es lo que impide que vuelva a narrar una cancelacion
        que no ocurre -- y ahorra una de las 20 peticiones del dia.
        """
        llm = LLMHandler(MagicMock())
        assert not await llm.can_handle(_datos("cancela las papas"))
        assert not await llm.can_handle(_datos("cancelar mi pedido"))


class TestElModeloVeElPedidoEntero:
    """
    Lo que el cliente cree que lleva pedido incluye lo que el bot acaba de
    proponerle. Al prompt entraba solo `session_data["cart"]`, asi que con un
    pedido recien propuesto se le enseñaba al modelo un carrito **vacio** y se
    le pedia que razonara sobre el.

    En vivo: "2 hamburguesas sin cebolla" -> "que sea sin salsa tambien" ->
    tres hamburguesas.
    """

    def _llm_con_propuesta(self, respuesta_del_modelo):
        proveedor = MagicMock()
        proveedor.build_system_prompt.return_value = "prompt"
        proveedor.build_context_prompt.return_value = "ctx"
        proveedor.generate_response = AsyncMock(return_value=respuesta_del_modelo)
        proveedor.should_confirm_product.return_value = False

        llm = LLMHandler(MagicMock())
        llm.update_session_state = AsyncMock()
        llm._get_available_products = AsyncMock(return_value=[
            {"id": "p-1", "name": "Hamburguesa", "price": 10.0, "description": ""},
        ])
        llm._find_product_in_db = AsyncMock(
            return_value={"id": "p-1", "name": "Hamburguesa", "price": 10.0}
        )
        return llm, proveedor

    def _sesion_con_dos_propuestas(self):
        estado = estado_pedido.proponer(estado_pedido.EstadoPedido(), [
            {"product_id": "p-1", "name": "Hamburguesa", "price": 10.0,
             "quantity": 2, "modifications": ["sin cebolla"]},
        ])
        return {
            "id": "sess-1",
            "current_state": "ordering",
            "session_data": estado_pedido.a_session_data(estado),
        }

    @pytest.mark.asyncio
    async def test_el_prompt_incluye_lo_propuesto(self):
        llm, proveedor = self._llm_con_propuesta(
            {"intention": "other", "products": [], "response_text": "ok"}
        )
        datos = _datos("que llevo?", session_data=self._sesion_con_dos_propuestas()["session_data"])

        with patch(
            "services.whatsapp.handlers.llm_handler.get_llm_provider",
            return_value=proveedor,
        ):
            await llm.handle(datos)

        enseñado = proveedor.build_context_prompt.call_args.kwargs["current_cart"]
        assert [i["name"] for i in enseñado] == ["Hamburguesa"], (
            "al modelo se le enseño un carrito vacio teniendo el cliente un pedido"
        )

    @pytest.mark.asyncio
    async def test_corregir_lo_propuesto_no_lo_duplica(self):
        """El fallo tal cual salio en vivo: 2 hamburguesas + correccion = 3."""
        llm, proveedor = self._llm_con_propuesta({
            "intention": "needs_confirmation",
            "products": [{"name": "Hamburguesa", "quantity": 1,
                          "modifications": ["sin salsa"]}],
            "response_text": "listo",
        })
        sesion = self._sesion_con_dos_propuestas()
        datos = _datos(
            "la hamburguesa que sea sin salsa tambien",
            session_data=sesion["session_data"],
        )

        with patch(
            "services.whatsapp.handlers.llm_handler.get_llm_provider",
            return_value=proveedor,
        ):
            await llm.handle(datos)

        guardado = llm.update_session_state.await_args_list[0].args[2]
        lineas = (guardado["cart"] or []) + (guardado["pending_products"] or [])
        total_hamburguesas = sum(
            i["quantity"] for i in lineas if i["name"] == "Hamburguesa"
        )
        assert total_hamburguesas == 2, (
            f"pidio dos y la correccion las dejo en {total_hamburguesas}"
        )



class TestLoQueSeDiceQuedaGuardado:
    """
    Lo que el bot dice haber hecho tiene que seguir en la base **cuando el turno
    ha terminado entero**, no solo justo despues de escribirlo.

    Sin esto, un turno podia guardar la correccion y pisarla dos lineas mas
    abajo. Es lo que hacia `_update_history`: reescribia session_data entero
    desde la copia leida al empezar el turno. El cliente leia "Modificado" y a
    la cocina llegaba el pedido sin corregir.
    """

    @pytest.mark.asyncio
    async def test_la_correccion_sobrevive_al_guardado_del_historial(self):
        import copy

        from tests.fake_supabase import seed_tenant

        fake = seed_tenant()
        fila = {
            "id": "sess-1", "tenant_id": "t", "customer_phone": "+1",
            "current_state": "ordering",
            "session_data": estado_pedido.a_session_data(
                estado_pedido.añadir(estado_pedido.EstadoPedido(), CARRITO)
            ),
        }
        fake.insert_row("conversation_sessions", fila)

        # Copia, como en produccion: la sesion se lee al empezar el turno y es
        # un objeto distinto del que vive en la base. Pasando la fila viva, el
        # pisoton es invisible -- sesion y base serian lo mismo.
        sesion = copy.deepcopy(fila)

        llm = LLMHandler(fake)
        respuesta = await llm._handle_modify_cart_item(
            [{"name": "Hamburguesa", "modifications": ["sin salsa"]}],
            "", sesion, "t", "+1", "es",
        )
        assert "sin salsa" in respuesta

        guardado = next(
            r for r in fake.rows("conversation_sessions") if r["id"] == "sess-1"
        )["session_data"]

        assert guardado["cart"][0]["modifications"] == ["sin salsa"], (
            "el bot dijo que lo modifico y en la base no esta: algo del mismo "
            "turno lo piso"
        )
        assert guardado.get("history"), "el historial tambien tenia que guardarse"


class TestComoEscribeLaGenteDeVerdad:
    """
    Frases enteras, con cortesias, como llegan por WhatsApp.

    Este bloque existe por un fallo que llego a produccion. La regla decia "es
    el pedido entero" solo si **todas** las palabras sobrantes estaban en una
    lista corta (pedido, orden, todo...). Cualquier cortesia la rompia:

        cliente > quiero cancelar todo y comenzar de nuevo la orden
        bot     > No encontre "quiero todo y comenzar nuevo orden" en tu carrito

    Fallaba hasta "quiero cancelar mi pedido". Las pruebas de entonces pasaban
    porque las escribi telegraficas -- probaban mis suposiciones, no como
    escribe la gente. De ahi que este bloque use frases largas a proposito.
    """

    CARRITO_DOS = [
        {"product_id": "p-1", "name": "Hamburguesa", "price": 10.0, "quantity": 1},
        {"product_id": "p-2", "name": "Papas", "price": 4.5, "quantity": 1},
    ]

    def _sesion(self):
        return estado_pedido.a_session_data(
            estado_pedido.añadir(estado_pedido.EstadoPedido(), self.CARRITO_DOS)
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mensaje", [
        "quiero cancelar todo y comenzar de nuevo la orden",   # la de produccion
        "quiero cancelar mi pedido",
        "mejor cancela todo por favor",
        "cancela todo",
        "cancelar",
        "por favor cancelame la orden completa",
        "ya no quiero nada, cancela el pedido",
    ])
    async def test_estas_frases_cancelan_el_pedido_entero(self, mensaje):
        handler = CancelarPedidoHandler(MagicMock())
        handler.update_session_state = AsyncMock()

        respuesta = await handler.handle(_datos(mensaje, self._sesion()))

        assert respuesta == t("order.cancelled", "es"), (
            f"{mensaje!r} no se entendio como cancelar el pedido"
        )
        estado, guardado = handler.update_session_state.await_args.args[1:3]
        assert guardado["cart"] == []
        assert estado == "initial"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mensaje,queda", [
        ("cancela las papas", "Hamburguesa"),
        ("quitame las papas por favor", "Hamburguesa"),
        # Lleva la palabra "pedido", pero nombra un producto: se le pregunta
        # antes al carrito que a la lista de palabras. Quitar una linea es
        # recuperable; vaciar el pedido, no.
        ("cancela las papas del pedido", "Hamburguesa"),
    ])
    async def test_estas_solo_quitan_lo_que_nombran(self, mensaje, queda):
        handler = CancelarPedidoHandler(MagicMock())
        handler.update_session_state = AsyncMock()

        await handler.handle(_datos(mensaje, self._sesion()))

        guardado = handler.update_session_state.await_args.args[2]
        assert [i["name"] for i in guardado["cart"]] == [queda], (
            f"{mensaje!r} se llevo por delante lo que el cliente no nombro"
        )

    @pytest.mark.asyncio
    async def test_nombrar_algo_que_no_se_tiene_sigue_sin_borrar_nada(self):
        handler = CancelarPedidoHandler(MagicMock())
        handler.update_session_state = AsyncMock()

        respuesta = await handler.handle(_datos("cancela la pizza", self._sesion()))

        handler.update_session_state.assert_not_awaited()
        assert "pizza" in respuesta


class TestUnSaludoSeSaluda:
    """
    El cliente dijo "hola" con un pedido a medias y recibio el volcado del
    pedido pendiente, sin saludo: WelcomeHandler exigia el estado `initial`, asi
    que un cliente que vuelve nunca era saludado y su mensaje caia en la
    respuesta por defecto.
    """

    @pytest.mark.asyncio
    async def test_saluda_y_enseña_lo_que_lleva(self):
        handler = WelcomeHandler(MagicMock())
        handler.update_session_state = AsyncMock()
        sesion = estado_pedido.a_session_data(
            estado_pedido.añadir(estado_pedido.EstadoPedido(), CARRITO)
        )
        datos = _datos("hola", sesion)
        datos["tenant_name"] = "Mi Tienda"

        assert await handler.can_handle(datos)
        respuesta = await handler.handle(datos)

        assert t("welcome.default", "es", store_name="Mi Tienda") in respuesta
        assert "Hamburguesa" in respuesta, "saluda pero no dice lo que lleva"

    @pytest.mark.asyncio
    async def test_saludar_no_mueve_la_conversacion_de_sitio(self):
        """
        `handle` escribia el estado `initial`. Con la conversacion en
        `ordering`, eso dejaria al "si" siguiente sin poder cerrar el pedido:
        CartConfirmationHandler solo acepta `viewing_cart` u `ordering`.
        """
        handler = WelcomeHandler(MagicMock())
        handler.update_session_state = AsyncMock()
        sesion = estado_pedido.a_session_data(
            estado_pedido.añadir(estado_pedido.EstadoPedido(), CARRITO)
        )
        datos = _datos("hola", sesion, estado="ordering")
        datos["tenant_name"] = "Mi Tienda"

        await handler.handle(datos)

        handler.update_session_state.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sin_pedido_saluda_como_siempre(self):
        handler = WelcomeHandler(MagicMock())
        handler.update_session_state = AsyncMock()
        datos = _datos("hola", {}, estado="initial")
        datos["tenant_name"] = "Mi Tienda"

        respuesta = await handler.handle(datos)

        assert t("welcome.options", "es") in respuesta


class TestQuienReclamaCadaPalabra:
    """Las fronteras entre handlers que se pisan las palabras clave."""

    @pytest.mark.asyncio
    async def test_cancelar_una_cita_no_es_cancelar_un_pedido(self):
        """
        "cancelar mi cita" contiene "cancelar". El orden de la cadena ya pone
        la agenda delante, pero esto lo deja dicho tambien aqui: reordenarla no
        puede convertir una cita cancelada en un pedido borrado.
        """
        handler = CancelarPedidoHandler(MagicMock())

        assert await handler.can_handle(_datos("cancelar"))
        assert not await handler.can_handle(_datos("cancelar mi cita"))

    @pytest.mark.asyncio
    async def test_cancelar_gana_a_descartar_lo_pendiente(self):
        """
        Con productos pendientes, "cancelar" casaba con `reject` y lo reclamaba
        ConfirmationHandler, que solo descarta la propuesta: el cliente pedia
        deshacerse de todo y se quedaba con el carrito entero debajo.
        """
        con_pendientes = estado_pedido.a_session_data(
            estado_pedido.proponer(
                estado_pedido.añadir(estado_pedido.EstadoPedido(), CARRITO),
                [{"product_id": "p-2", "name": "Papas", "price": 4.5, "quantity": 1}],
            )
        )
        datos = _datos("cancelar", session_data=con_pendientes)

        assert not await ConfirmationHandler(MagicMock()).can_handle(datos)
        assert await CancelarPedidoHandler(MagicMock()).can_handle(datos)

    @pytest.mark.asyncio
    async def test_un_no_sigue_siendo_de_quien_descarta(self):
        """
        La otra mitad del contrato anterior. El resumen dice "responde *no*
        para seguir agregando": si "no" acabara en CancelarPedidoHandler, el
        cliente que queria añadir algo mas perderia el pedido entero.
        """
        con_pendientes = estado_pedido.a_session_data(
            estado_pedido.proponer(estado_pedido.EstadoPedido(), CARRITO)
        )
        datos = _datos("no", session_data=con_pendientes)

        assert await ConfirmationHandler(MagicMock()).can_handle(datos)
        assert not await CancelarPedidoHandler(MagicMock()).can_handle(datos)

    @pytest.mark.asyncio
    async def test_eso_es_todo_sin_carrito_no_lo_reclama_nadie(self):
        """
        Sin nada pedido, "listo" no cierra nada: tiene que seguir bajando la
        cadena en vez de contestar un resumen vacio.
        """
        handler = CierreDePedidoHandler(MagicMock())
        assert not await handler.can_handle(_datos("eso es todo", session_data={}))

    @pytest.mark.asyncio
    async def test_eso_es_todo_cierra_tambien_lo_solo_propuesto(self):
        """
        Con una propuesta del LLM delante y el carrito todavia vacio, "eso es
        todo" la esta dando por buena. Mirando solo el carrito, el cierre se
        quedaba sin dueño y el cliente recibia el menu generico.
        """
        solo_pendientes = estado_pedido.a_session_data(
            estado_pedido.proponer(estado_pedido.EstadoPedido(), CARRITO)
        )
        handler = CierreDePedidoHandler(MagicMock())
        handler.update_session_state = AsyncMock()
        datos = _datos("eso es todo", session_data=solo_pendientes)

        assert await handler.can_handle(datos)
        respuesta = await handler.handle(datos)
        assert "Hamburguesa" in respuesta

        guardado = handler.update_session_state.await_args.args[2]
        assert guardado["cart"], "lo propuesto no llego al carrito"
        assert not guardado["pending_products"]

    @pytest.mark.asyncio
    async def test_un_producto_que_contiene_una_palabra_de_cierre(self):
        """
        `finish` se compara por palabra entera. "tienes todo" contiene "es
        todo" como subcadena, y un cliente preguntando eso no esta cerrando su
        pedido.
        """
        handler = CierreDePedidoHandler(MagicMock())
        assert not await handler.can_handle(_datos("tienes todo?"))
