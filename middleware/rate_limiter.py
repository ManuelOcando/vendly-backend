from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request, Response
import logging

logger = logging.getLogger(__name__)

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

# Manejador de 429. Registra el acierto antes de responder: sin esto los
# limites saltan en silencio y no hay forma de saber si alguien esta chocando
# con ellos, ni si el limite es el correcto. Existia como
# `custom_rate_limit_handler` pero main.py registraba el de slowapi a secas,
# asi que nunca llego a ejecutarse.
async def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded):
    logger.warning(
        "Rate limit alcanzado: clave=%s ruta=%s limite=%s",
        get_remote_address(request),
        request.url.path,
        getattr(exc, "detail", "?"),
    )
    return _rate_limit_exceeded_handler(request, exc)
