"""
Seudonimos y longitudes para los logs, en vez de datos personales.

Los logs del backend van a Render: se retienen, los lee cualquiera con acceso al
panel, y nadie los ha clasificado nunca como datos personales. Escribir alli el
telefono de un cliente y lo que escribio crea una segunda base de datos que nadie
administra, sin control de acceso propio ni borrado. Eso es lo que arregla este
modulo.

Por que HMAC y no un hash a secas. Un numero de telefono vive en un espacio
diminuto -- unos cientos de millones de posibilidades -- y una maquina normal
calcula miles de millones de SHA-256 por segundo. Un sha256(numero) se revierte
construyendo la tabla entera en segundos, asi que hashear no protege: disfraza.
Con HMAC hace falta la clave para construir esa tabla.

El resultado es un seudonimo, no un anonimo: el mismo numero da siempre el mismo
codigo, que es justo lo que permite seguir una conversacion entre lineas de log
cuando un comerciante dice "un cliente escribio y el bot no contesto".
"""
import hashlib
import hmac
import logging
import os
from typing import Optional

from config import get_settings

logger = logging.getLogger(__name__)

# Etiqueta de separacion de proposito. La clave de los logs se deriva de la de
# cifrado en vez de ser la misma: una clave no debe hacer dos trabajos, porque
# si un uso se rompe o se filtra arrastra al otro. Derivar evita ademas tener
# que gestionar otra variable de entorno.
_ETIQUETA = b"vendly-log-pseudonym"

# Sin clave configurada (desarrollo) los seudonimos salen de una sal aleatoria
# por proceso: siguen siendo consistentes dentro de una ejecucion, que es lo que
# hace falta para depurar, y no sobreviven al reinicio. En produccion la clave es
# obligatoria, asi que este camino no se da alli.
_SAL_DE_PROCESO = os.urandom(32)

_LONGITUD = 6


def _clave_de_logs(clave: Optional[str] = None) -> bytes:
    if clave is None:
        clave = get_settings().WHATSAPP_TOKEN_ENCRYPTION_KEY

    if not clave:
        return hmac.new(_SAL_DE_PROCESO, _ETIQUETA, hashlib.sha256).digest()

    material = clave.encode() if isinstance(clave, str) else clave
    return hmac.new(material, _ETIQUETA, hashlib.sha256).digest()


def tel(phone, *, clave: Optional[str] = None) -> str:
    """
    El seudonimo estable de un telefono: `tel:a3f9c1`.

    Acepta None y cadenas vacias porque en los logs aparecen los dos, y una
    excepcion aqui tumbaria la linea que se estaba intentando registrar.
    """
    if not phone:
        return "tel:-"

    texto = str(phone).strip()
    firma = hmac.new(_clave_de_logs(clave), texto.encode(), hashlib.sha256)
    return f"tel:{firma.hexdigest()[:_LONGITUD]}"


def preview(texto) -> str:
    """
    Cuanto ocupa un texto, nunca que dice: `<48 caracteres>`.

    Se usa donde antes se registraba el mensaje del cliente o la respuesta del
    bot. La longitud basta para distinguir "no genero respuesta" de "genero una
    respuesta vacia" de "genero un ladrillo", que es para lo que se miraban.
    """
    if texto is None:
        return "<nada>"
    return f"<{len(str(texto))} caracteres>"
