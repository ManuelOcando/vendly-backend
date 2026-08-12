"""
Cifrado de los access_token de Meta guardados en whatsapp_configs.

El token de la Cloud API no es configuracion: con el se envian mensajes de
WhatsApp en nombre del negocio, a sus clientes, desde su numero. Es una
credencial de suplantacion y estaba guardada en claro.

Que protege esto y que no. La clave vive en el entorno de Render, separada de
la base de datos, y esa separacion es todo el mecanismo:

  * Si se filtra el contenido de la base -- un backup, un volcado, un
    compromiso del lado de Supabase, o una clave service_role publicada, que es
    exactamente lo que paso en este proyecto -- lo filtrado es ruido.
  * Si comprometen el backend no protege nada, porque alli estan la clave y el
    acceso a la base a la vez. Defensa en profundidad, no una barrera.

Fernet (AES-128-CBC + HMAC-SHA256) cifra y autentica: un texto manipulado no
descifra, falla. Lleva IV aleatorio, asi que cifrar dos veces el mismo token da
dos textos distintos; es lo esperado, no un error.
"""
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from config import get_settings

logger = logging.getLogger(__name__)


class TokenEncryptionUnavailable(RuntimeError):
    """No hay WHATSAPP_TOKEN_ENCRYPTION_KEY configurada.

    Se lanza al cifrar, nunca al descifrar. Preferimos que guardar falle a
    guardar en claro creyendo que ciframos.
    """


def _fernet(key: Optional[str] = None) -> Fernet:
    """La clave explicita gana sobre la del entorno; los tests la pasan directa."""
    key = key or get_settings().WHATSAPP_TOKEN_ENCRYPTION_KEY
    if not key:
        raise TokenEncryptionUnavailable(
            "WHATSAPP_TOKEN_ENCRYPTION_KEY no esta configurada. Generala con "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"`"
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(plain: str, *, key: Optional[str] = None) -> str:
    """Cifra un token. Sin clave configurada falla, a proposito."""
    if not plain:
        return plain
    return _fernet(key).encrypt(plain.encode()).decode()


def decrypt_token(stored: str, *, key: Optional[str] = None) -> str:
    """
    Descifra un token, tolerando que todavia este en claro.

    La tolerancia es deliberada y temporal. Permite desplegar el codigo antes
    de convertir las filas existentes: durante esa ventana conviven valores
    cifrados y en claro, y el bot sigue respondiendo. Sin ella el despliegue y
    el backfill tendrian que ser atomicos, que es como se deja un negocio sin
    WhatsApp a media tarde.

    Una vez hecho el backfill y confirmado que no queda nada en claro, esto
    deberia endurecerse para que un valor no cifrado sea un error.
    """
    if not stored:
        return stored

    try:
        return _fernet(key).decrypt(stored.encode()).decode()
    except InvalidToken:
        # No es un texto Fernet: lo damos por un token en claro pendiente de
        # convertir. No registramos el valor, obviamente.
        logger.warning(
            "access_token sin cifrar en whatsapp_configs (%d caracteres). "
            "Pendiente de backfill: scripts/encrypt_whatsapp_tokens.py",
            len(stored),
        )
        return stored
    except TokenEncryptionUnavailable:
        # En desarrollo sin clave, leer sigue funcionando; escribir no.
        logger.warning(
            "Sin WHATSAPP_TOKEN_ENCRYPTION_KEY: el access_token se lee tal cual."
        )
        return stored


def looks_encrypted(stored: str, *, key: Optional[str] = None) -> bool:
    """Si el valor descifra con nuestra clave. Lo usan el backfill y sus tests."""
    if not stored:
        return False
    try:
        _fernet(key).decrypt(stored.encode())
        return True
    except (InvalidToken, TokenEncryptionUnavailable):
        return False
