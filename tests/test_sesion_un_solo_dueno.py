"""
Nadie escribe `session_data` entero fuera de db/sesion.py.

El guardia existe por un fallo que costo tres semanas encontrar y que ninguna
prueba podia ver.

Todo el estado de la conversacion vive en una sola columna JSON: carrito,
historial, idioma, pendientes. `_update_history` cogia la copia leida **al
empezar el turno**, le añadia los dos mensajes y reescribia la columna entera.
En un turno que corregia el pedido, el orden de las escrituras era:

    1. se guarda el pedido corregido  -> (sin cebolla, sin salsa)
    2. se guarda el historial         -> (sin cebolla)          <- pisa a la 1

El cliente leia "Modificado" y a la cocina llegaba el pedido sin corregir.

La suite estaba verde porque esa segunda escritura iba **directa a la tabla**,
saltandose `update_session_state` -- que es lo que las pruebas espian -- y el
guardia de estado_pedido solo mira `session_data[...] = ...` y diccionarios
literales pasados a `update_session_state`. Esto no era ninguna de las dos.
"""
import ast
from pathlib import Path
from typing import List

import pytest

RAIZ = Path(__file__).resolve().parent.parent
DUEÑO = RAIZ / "db" / "sesion.py"


def escrituras_enteras(fuente: str) -> List[str]:
    """
    Llamadas `...table("conversation_sessions").update({... "session_data" ...})`.

    Se mira el arbol y no el texto porque la llamada ocupa varias lineas y
    porque hay que distinguirla de un update que solo toca `last_message_at`,
    que es inofensivo.
    """
    hallazgos = []
    for nodo in ast.walk(ast.parse(fuente)):
        if not isinstance(nodo, ast.Call):
            continue
        if not (isinstance(nodo.func, ast.Attribute) and nodo.func.attr == "update"):
            continue
        if not nodo.args or not isinstance(nodo.args[0], ast.Dict):
            continue

        # ¿La cadena de llamadas nombra la tabla de sesiones?
        texto = ast.dump(nodo.func)
        if "conversation_sessions" not in texto:
            continue

        claves = {
            k.value for k in nodo.args[0].keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        if "session_data" in claves:
            hallazgos.append(f"linea {nodo.lineno}")
    return hallazgos


class TestSoloUnSitioEscribeLaSesion:
    def test_nadie_reescribe_la_columna_entera(self):
        infractores = []
        for ruta in RAIZ.rglob("*.py"):
            if any(x in ruta.parts for x in ("venv", "tests", "__pycache__")):
                continue
            if ruta == DUEÑO:
                continue
            for hallazgo in escrituras_enteras(
                ruta.read_text(encoding="utf-8", errors="ignore")
            ):
                infractores.append(f"{ruta.relative_to(RAIZ)}:{hallazgo}")

        assert not infractores, (
            "Estos sitios reescriben session_data entero y se comeran lo que "
            "otra escritura del mismo turno acabe de guardar. Usa "
            "db/sesion.py:merge_session_data, que relee y fusiona:\n  "
            + "\n  ".join(infractores)
        )

    def test_el_detector_reconoce_la_infraccion_original(self):
        """La forma exacta que tenia _update_history."""
        assert escrituras_enteras(
            'self.db.table("conversation_sessions").update({\n'
            '    "session_data": session_data,\n'
            '    "updated_at": ahora,\n'
            '}).eq("id", session_id).execute()'
        )

    def test_el_detector_deja_pasar_lo_inofensivo(self):
        # Solo la hora del ultimo mensaje: no toca el estado de nadie.
        assert not escrituras_enteras(
            'self.db.table("conversation_sessions").update({'
            ' "last_message_at": ahora }).eq("id", sid).execute()'
        )
        # Y otra tabla cualquiera.
        assert not escrituras_enteras(
            'self.db.table("orders").update({ "session_data": x }).execute()'
        )


class TestLaFusionSuma:
    """Dos escrituras del mismo turno se suman en vez de pisarse."""

    def test_el_segundo_parche_no_borra_el_primero(self):
        from unittest.mock import MagicMock

        from db.sesion import merge_session_data

        guardado = {"session_data": {"cart": [{"name": "Hamburguesa"}]}}
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            MagicMock(data=[guardado])
        )

        merge_session_data(db, "s-1", patch={"history": ["hola"]})

        escrito = db.table.return_value.update.call_args.args[0]["session_data"]
        assert escrito["history"] == ["hola"]
        assert escrito["cart"], "la segunda escritura se comio el carrito"

    def test_sin_estado_no_se_toca_el_estado(self):
        """
        Guardar el historial no puede mover la conversacion de sitio. Esa era
        justo la razon por la que _update_history escribia por su cuenta.
        """
        from unittest.mock import MagicMock

        from db.sesion import merge_session_data

        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
            MagicMock(data=[{"session_data": {}}])
        )

        merge_session_data(db, "s-1", patch={"history": []})

        assert "current_state" not in db.table.return_value.update.call_args.args[0]
