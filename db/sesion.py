"""
El unico sitio que escribe `conversation_sessions.session_data`.

Existe por un fallo concreto. Todo el estado de la conversacion vive en una sola
columna JSON -- carrito, historial, idioma, pendientes --, asi que "guardar el
historial" significaba reescribir tambien el carrito. `_update_history` cogia la
copia leida **al empezar el turno**, le añadia los dos mensajes y reescribia la
columna entera:

    1. el turno guarda el pedido corregido   -> (sin cebolla, sin salsa)
    2. el turno guarda el historial          -> (sin cebolla)          <- pisado

El cliente leia "Modificado" y a la cocina llegaba el pedido sin corregir. Ni un
error en los logs, y la suite en verde: la segunda escritura iba directa a la
tabla, saltandose la funcion que las pruebas espian.

La cura es no dejar que nadie escriba la columna entera. Aqui se relee lo que
hay **ahora** y se fusiona el parche encima, asi que dos escrituras del mismo
turno se suman en vez de pisarse. Hay un guardia en tests que lo mantiene.
"""
from typing import Any, Dict, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def read_session_data(db, session_id: str) -> Dict[str, Any]:
    """Lo que hay guardado ahora mismo, o {} si no se puede leer."""
    try:
        result = db.table("conversation_sessions").select(
            "session_data"
        ).eq("id", session_id).limit(1).execute()
        if result.data:
            return result.data[0].get("session_data") or {}
    except Exception as e:
        logger.error("No se pudo leer session_data de %s: %s", session_id, e, exc_info=True)
    return {}


def merge_session_data(
    db,
    session_id: str,
    patch: Optional[Dict[str, Any]] = None,
    state: Optional[str] = None,
) -> None:
    """
    Fusiona `patch` en session_data, sin tocar lo que no nombra.

    `state` es opcional a proposito: guardar el historial no debe mover el
    estado de la conversacion, y esa era justo la razon por la que
    `_update_history` escribia por su cuenta.
    """
    if not session_id:
        return

    update: Dict[str, Any] = {"updated_at": datetime.now().isoformat()}
    if state is not None:
        update["current_state"] = state
    if patch:
        update["session_data"] = {**read_session_data(db, session_id), **patch}

    try:
        db.table("conversation_sessions").update(update).eq("id", session_id).execute()
    except Exception as e:
        logger.error("No se pudo guardar la sesion %s: %s", session_id, e, exc_info=True)
