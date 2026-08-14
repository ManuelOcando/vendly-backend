"""
Si el LLM esta respondiendo, y si no, por que.

Existe por una noche concreta. El bot dejo de entender modificaciones, de
entender "eso es todo" y de saber cancelar. Parecia una regresion del ultimo
despliegue y se fueron veinte minutos buscandola en el codigo. No era eso: se
habia agotado la cuota diaria gratuita de Gemini -- veinte peticiones -- y
LLMHandler.handle hacia lo correcto, ceder a la cadena determinista.

Ceder es correcto; **hacerlo en silencio no**. El unico rastro era un
`CRITICAL ERROR` en los logs de Render, donde nadie mira, y el sintoma que ve
el comerciante es un bot mas tonto sin ninguna explicacion.

Esto no arregla la cuota: la hace visible. Un fallo que se ve se atiende; uno
que no, se persigue.

En memoria y por proceso, a proposito: es un diagnostico de "como esta ahora
mismo esta instancia", no un historico. Para eso estan los logs.
"""
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Lo que Google, OpenAI y compañia dicen cuando se acaba la cuota o se pide
# demasiado deprisa. Se busca en el texto porque cada proveedor lanza su propia
# excepcion y no hay un tipo comun que capturar.
_SEÑALES_DE_CUOTA = (
    "quota", "resource_exhausted", "rate limit", "ratelimit",
    "429", "too many requests", "exceeded your current quota",
)

_estado: Dict[str, Any] = {
    "ultimo_exito": None,
    "ultimo_fallo": None,
    "motivo": None,
    "es_cuota": False,
    "fallos_seguidos": 0,
}


def _parece_cuota(texto: str) -> bool:
    minuscula = texto.lower()
    return any(señal in minuscula for señal in _SEÑALES_DE_CUOTA)


def registrar_exito() -> None:
    """El LLM contesto. Borra el fallo anterior: ya no describe el presente."""
    _estado.update(
        ultimo_exito=time.time(),
        ultimo_fallo=None,
        motivo=None,
        es_cuota=False,
        fallos_seguidos=0,
    )


def registrar_fallo(error: BaseException) -> None:
    """
    El LLM no contesto. Se guarda el motivo y se registra en el log de forma
    que se pueda encontrar buscando una sola palabra.
    """
    texto = f"{type(error).__name__}: {error}"
    es_cuota = _parece_cuota(texto)

    _estado.update(
        ultimo_fallo=time.time(),
        # Recortado: los errores de cuota de Google traen media pagina de
        # detalles de facturacion.
        motivo=texto[:300],
        es_cuota=es_cuota,
        fallos_seguidos=_estado["fallos_seguidos"] + 1,
    )

    if es_cuota:
        logger.error(
            "LLM_DEGRADADO cuota agotada (%d fallos seguidos). El bot responde "
            "con la cadena determinista: no entiende modificaciones ni cancelar. "
            "Detalle: %s",
            _estado["fallos_seguidos"], _estado["motivo"],
        )
    else:
        logger.error(
            "LLM_DEGRADADO (%d fallos seguidos): %s",
            _estado["fallos_seguidos"], _estado["motivo"],
        )


def informe() -> Dict[str, Any]:
    """
    Como esta el LLM, para /health.

    `degradado` es el campo que importa: dice si ahora mismo los clientes estan
    hablando con la cadena determinista en vez de con el modelo.
    """
    ahora = time.time()
    fallo = _estado["ultimo_fallo"]

    salida: Dict[str, Any] = {
        "degradado": fallo is not None,
        "fallos_seguidos": _estado["fallos_seguidos"],
    }

    if fallo is None:
        if _estado["ultimo_exito"]:
            salida["ultimo_exito_hace_segundos"] = round(ahora - _estado["ultimo_exito"], 1)
        return salida

    salida["ultimo_fallo_hace_segundos"] = round(ahora - fallo, 1)
    salida["motivo"] = _estado["motivo"]
    salida["causa"] = "cuota_agotada" if _estado["es_cuota"] else "error"

    if _estado["es_cuota"]:
        salida["que_hacer"] = (
            "El plan gratuito de Gemini permite 20 peticiones al dia. Subir de "
            "plan, o cambiar LLM_PROVIDER a openrouter."
        )

    return salida


def reiniciar() -> None:
    """Solo para los tests: el estado vive todo el proceso."""
    _estado.update(
        ultimo_exito=None, ultimo_fallo=None, motivo=None,
        es_cuota=False, fallos_seguidos=0,
    )
