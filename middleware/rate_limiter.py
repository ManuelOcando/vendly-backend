from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request, Response
import logging

logger = logging.getLogger(__name__)


def client_ip(request: Request) -> str:
    """
    La direccion del cliente que este no puede elegir.

    slowapi trae get_remote_address, que devuelve request.client.host. Detras
    de este despliegue eso resulta ser la entrada mas a la izquierda de
    X-Forwarded-For - uvicorn hace caso a las cabeceras de proxy - y esa
    entrada la escribe quien llama, porque el borde de arriba *anade* a la
    cadena en lugar de reemplazarla. Medido contra produccion:

        sin cabeceras propias   -> clave 159.26.98.237   (la IP real)
        mandando X-Forwarded-For: 203.0.113.7
                                -> clave 203.0.113.7     (el invento)

    Con esa clave, cualquier limite se evade variando una cabecera por
    peticion, y lo unico que aporta es la apariencia de proteccion.

    CF-Connecting-IP no tiene ese problema: Cloudflare la sobrescribe en cada
    peticion, y un intento de mandarla desde fuera se corta en el borde con un
    403 antes de llegar aqui - comprobado. Por eso es la clave.

    El respaldo a get_remote_address es para desarrollo local y para cualquier
    ruta que no pase por Cloudflare; ahi vuelve a ser falsificable, asi que se
    deja constancia en el log para que no pase inadvertido si empieza a ocurrir
    en produccion.
    """
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()

    fallback = get_remote_address(request)
    logger.debug(
        "Sin CF-Connecting-IP en %s; clave de respaldo %s (falsificable)",
        request.url.path,
        fallback,
    )
    return fallback


# Techo general para todo lo que pase por SlowAPIMiddleware. Es holgado a
# proposito: no busca acotar el uso normal - una pagina del dashboard dispara
# varias llamadas - sino cortar la inundacion desde un solo origen. Los
# endpoints que cuestan mas que una consulta llevan su propio limite, mas
# estrecho, con @limiter.limit.
DEFAULT_LIMITS = ["240/minute"]

limiter = Limiter(key_func=client_ip, default_limits=DEFAULT_LIMITS)


# Manejador de 429. Registra el acierto antes de responder: sin esto los
# limites saltan en silencio y no hay forma de saber si alguien esta chocando
# con ellos, ni si el limite es el correcto. Existia como
# `custom_rate_limit_handler` pero main.py registraba el de slowapi a secas,
# asi que nunca llego a ejecutarse.
#
# Sincrono a proposito, y esto importa: SlowAPIMiddleware corre en contexto
# sincrono y descarta el manejador registrado si es una corrutina
# ("cannot execute asynchronous code in a synchronous middleware"), cayendo al
# de slowapi. Siendo async, los 429 del limite global - que son casi todos -
# volverian a no dejar rastro.
def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded):
    logger.warning(
        "Rate limit alcanzado: clave=%s ruta=%s limite=%s",
        client_ip(request),
        request.url.path,
        getattr(exc, "detail", "?"),
    )
    return _rate_limit_exceeded_handler(request, exc)
