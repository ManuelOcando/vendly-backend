"""
Cuando el modelo parte una modificacion en un producto aparte.

Conversacion real del 13/08/2026, 22:04. El cliente escribio "Ponte otra
hamburguesa sin lechuga y sin tomate" y el bot respondio:

    ✅ hamburguesa
    Tu carrito: hamburguesa x1 - $10.00
    ⚠️ No encontre: sin tomate: No encontre "sin tomate"

Dos cosas mal. El modelo devolvio {"name": "sin tomate"} como si fuera un
producto -- ningun catalogo lo tiene --, y de paso la hamburguesa entro sin
ninguna modificacion: el cliente la pidio sin tomate y le habria llegado con
tomate.

Se arregla en el codigo y no en el prompt porque el prompt no da garantias: por
bien redactado que este, el modelo volvera a partirlo alguna vez.
"""
import pytest

from services.whatsapp.handlers.llm_handler import (
    parece_modificacion,
    reasignar_modificaciones,
)


class TestQueCuentaComoModificacion:
    @pytest.mark.parametrize("nombre", [
        "sin tomate", "sin lechuga", "con todo", "extra queso",
        "sem tomate", "com tudo", "without onion", "with cheese", "no onion",
    ])
    def test_los_inicios_habituales_en_los_tres_idiomas(self, nombre):
        assert parece_modificacion(nombre)

    @pytest.mark.parametrize("nombre", [
        "hamburguesa", "perro caliente", "papas fritas", "conejo", "sincronizada",
    ])
    def test_un_producto_no_lo_es(self, nombre):
        """
        "conejo" empieza por "con" y "sincronizada" por "sin": por eso se compara
        con el espacio detras y no como prefijo suelto.
        """
        assert not parece_modificacion(nombre)

    @pytest.mark.parametrize("nombre", ["", None, "   "])
    def test_lo_vacio_no_revienta(self, nombre):
        assert not parece_modificacion(nombre)


class TestSeDevuelvenAlProductoAnterior:
    def test_la_conversacion_que_lo_destapo(self):
        """Lo que el modelo devolvio a las 22:04."""
        resultado = reasignar_modificaciones([
            {"name": "hamburguesa", "quantity": 1, "modifications": ["sin lechuga"]},
            {"name": "sin tomate"},
        ])

        assert len(resultado) == 1, "sin tomate seguia contando como producto"
        assert resultado[0]["modifications"] == ["sin lechuga", "sin tomate"]

    def test_varias_seguidas_se_acumulan(self):
        resultado = reasignar_modificaciones([
            {"name": "hamburguesa"},
            {"name": "sin cebolla"},
            {"name": "sin tomate"},
            {"name": "extra queso"},
        ])
        assert len(resultado) == 1
        assert resultado[0]["modifications"] == ["sin cebolla", "sin tomate", "extra queso"]

    def test_cada_una_va_a_su_producto(self):
        resultado = reasignar_modificaciones([
            {"name": "hamburguesa"},
            {"name": "sin cebolla"},
            {"name": "perro caliente"},
            {"name": "con todo"},
        ])
        assert [p["name"] for p in resultado] == ["hamburguesa", "perro caliente"]
        assert resultado[0]["modifications"] == ["sin cebolla"]
        assert resultado[1]["modifications"] == ["con todo"]

    def test_una_modificacion_sin_producto_delante_se_deja_pasar(self):
        """
        Acaba en el "no encontre" de siempre, y es lo correcto. Pasa cuando el
        cliente se refiere a algo que ya esta en el carrito ("ponte sin
        tomate"): descartarla en silencio haria que el bot contestara con un
        visto bueno y el carrito sin tocar, el cliente creeria que se aplico, y
        recibiria el tomate igual.
        """
        assert reasignar_modificaciones([{"name": "sin tomate"}]) == [{"name": "sin tomate"}]

    def test_lo_que_ya_venia_bien_no_se_toca(self):
        entrada = [{"name": "hamburguesa", "quantity": 2,
                    "modifications": ["sin cebolla"]}]
        assert reasignar_modificaciones(entrada) == entrada

    def test_no_muta_la_entrada(self):
        """La lista viene del modelo y se registra tal cual mas arriba."""
        entrada = [{"name": "hamburguesa", "modifications": ["sin lechuga"]},
                   {"name": "sin tomate"}]
        reasignar_modificaciones(entrada)
        assert entrada[0]["modifications"] == ["sin lechuga"]
        assert len(entrada) == 2

    @pytest.mark.parametrize("entrada", [None, []])
    def test_lo_vacio_devuelve_vacio(self, entrada):
        assert reasignar_modificaciones(entrada) == []
