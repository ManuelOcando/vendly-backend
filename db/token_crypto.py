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

    Preferimos que guardar falle a guardar en claro creyendo que ciframos, y que
    leer falle a devolver texto cifrado que acabaria enviado a Meta.
    """


class TokenDecryptionFailed(RuntimeError):
    """El valor guardado no descifra con la clave actual.

    Dos causas posibles, y el mensaje las nombra: la fila sigue en claro (falta
    el backfill), o la clave del entorno no es la que la cifro.
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
    Descifra un token. Un valor que no descifra es un error, no un aviso.

    Durante el despliegue del cifrado esto toleraba texto plano y lo devolvia
    tal cual, para que el codigo pudiera desplegarse antes de convertir las
    filas y el bot no se quedara mudo en la ventana intermedia. El backfill se
    hizo el 13/08/2026 y no queda nada en claro, asi que la tolerancia se
    retiro.

    Por que devolver el valor tal cual era peligroso a largo plazo: si la clave
    de Render se rota sin volver a cifrar, cada token deja de descifrar. Con la
    tolerancia, el backend le mandaria a Meta el texto cifrado, Meta contestaria
    401, y eso se lee igual que un token caducado -- se perderian horas mirando
    en Meta un problema que esta en la clave. Fallando aqui, el motivo aparece
    en la primera linea del log.

    Los llamantes ya estan preparados: los catorce que leen dentro de un try
    registran y siguen sin enviar, que es lo correcto -- no enviar es mejor que
    enviar basura en nombre del negocio. Los endpoints lo convierten en un 503
    legible via el manejador de main.py.
    """
    if not stored:
        return stored

    try:
        return _fernet(key).decrypt(stored.encode()).decode()
    except InvalidToken as e:
        # Nunca el valor en el mensaje, solo su longitud.
        raise TokenDecryptionFailed(
            f"El access_token guardado no descifra con la clave actual "
            f"({len(stored)} caracteres). O la fila quedo en claro -- ejecutar "
            f"scripts/encrypt_whatsapp_tokens.py --apply -- o "
            f"WHATSAPP_TOKEN_ENCRYPTION_KEY no es la que lo cifro."
        ) from e


def looks_encrypted(stored: str, *, key: Optional[str] = None) -> bool:
    """Si el valor descifra con nuestra clave. Lo usan el backfill y sus tests."""
    if not stored:
        return False
    try:
        _fernet(key).decrypt(stored.encode())
        return True
    except (InvalidToken, TokenEncryptionUnavailable):
        return False
