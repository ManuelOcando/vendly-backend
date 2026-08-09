"""
Verificacion de la firma de los webhooks de Meta.

Meta firma cada POST con un HMAC-SHA256 del cuerpo crudo usando el App Secret
de la app, y manda el resultado en la cabecera X-Hub-Signature-256. Sin esa
comprobacion el endpoint acepta cualquier JSON, y la URL del webhook es
publica: cualquiera podria inyectar mensajes con el phone_number_id de un
tenant ajeno y hacer que el bot conteste, cree pedidos, mande WhatsApps con el
token de ese tenant y consuma cuota de LLM en su nombre.

https://developers.facebook.com/docs/graph-api/webhooks/getting-started#validate-payloads
"""
import hashlib
import hmac
from typing import Optional

SIGNATURE_HEADER = "X-Hub-Signature-256"
_PREFIX = "sha256="


def sign_payload(app_secret: str, raw_body: bytes) -> str:
    """
    La cabecera que Meta enviaria para este cuerpo. Se usa para verificar y,
    en los tests, para construir peticiones legitimas.
    """
    digest = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return _PREFIX + digest


def is_valid_signature(
    app_secret: str,
    raw_body: bytes,
    header: Optional[str],
) -> bool:
    """
    True solo si `header` es la firma que corresponde a `raw_body`.

    Falla cerrado ante todo lo demas: secreto sin configurar, cabecera ausente,
    prefijo distinto de "sha256=" o hexadecimal invalido. La comparacion final
    es en tiempo constante sobre los digests en crudo - comparar las cadenas
    hex con `==` filtraria, byte a byte, cuanto prefijo acerto quien prueba.
    """
    if not app_secret or not header:
        return False

    if not header.startswith(_PREFIX):
        return False

    try:
        provided = bytes.fromhex(header[len(_PREFIX):])
    except ValueError:
        return False

    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).digest()
    return hmac.compare_digest(expected, provided)
