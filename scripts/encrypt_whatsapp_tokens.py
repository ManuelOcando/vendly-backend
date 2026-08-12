#!/usr/bin/env python3
"""
Convierte a cifrado los access_token que siguen en claro en whatsapp_configs.

Se ejecuta UNA vez, despues de desplegar el codigo que cifra y de poner
WHATSAPP_TOKEN_ENCRYPTION_KEY en el entorno. Ese orden importa:

  1. Codigo desplegado. Lee tanto claro como cifrado (decrypt_token es
     tolerante), asi que nada se rompe mientras tanto.
  2. Clave en el entorno.
  3. Este script.

Al reves no funciona: convertir antes de desplegar deja al backend viejo
leyendo texto cifrado y mandandoselo a Meta, que responde 401, y el bot deja de
contestar a los clientes.

Por defecto no escribe nada: enseña lo que haria. Para aplicarlo de verdad:

    python -m scripts.encrypt_whatsapp_tokens --apply

Es idempotente. Una fila ya cifrada se salta, asi que volver a ejecutarlo no
hace daño ni cifra dos veces.
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from db.supabase import get_supabase_client
from db.token_crypto import encrypt_token, looks_encrypted

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

TABLE = "whatsapp_configs"


def convertir(aplicar: bool) -> int:
    db = get_supabase_client()

    # Acceso directo a la tabla a proposito: este es el unico sitio que debe
    # ver el valor crudo sin descifrarlo, porque su trabajo es distinguir si ya
    # esta cifrado. Por eso vive en scripts/ y no detras de db/whatsapp_config.py.
    result = db.table(TABLE).select("id, tenant_id, access_token").execute()
    filas = result.data or []

    logger.info("%d fila(s) en %s", len(filas), TABLE)

    convertidas = 0
    for fila in filas:
        tenant_id = fila.get("tenant_id")
        token = fila.get("access_token") or ""

        if not token:
            logger.info("  %s: sin token, se salta", tenant_id)
            continue

        if looks_encrypted(token):
            logger.info("  %s: ya cifrado, se salta", tenant_id)
            continue

        # Nunca el valor, solo su longitud.
        logger.info("  %s: en claro (%d caracteres) -> cifrar", tenant_id, len(token))

        if aplicar:
            cifrado = encrypt_token(token)

            # Comprobacion antes de escribir: si esto fallara guardariamos algo
            # que no sabemos recuperar, y el comerciante perderia su WhatsApp.
            from db.token_crypto import decrypt_token
            if decrypt_token(cifrado) != token:
                raise RuntimeError(
                    f"El cifrado de {tenant_id} no se recupera igual. Nada escrito."
                )

            db.table(TABLE).update({"access_token": cifrado}).eq(
                "id", fila["id"]
            ).execute()
            logger.info("     hecho (%d caracteres cifrados)", len(cifrado))

        convertidas += 1

    return convertidas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Escribir de verdad. Sin esto solo se muestra lo que se haria.",
    )
    args = parser.parse_args()

    convertidas = convertir(aplicar=args.apply)

    if not args.apply:
        logger.info(
            "\nSimulacion: %d fila(s) por convertir. "
            "Repite con --apply para escribirlas.", convertidas
        )
    else:
        logger.info("\n%d fila(s) convertidas.", convertidas)


if __name__ == "__main__":
    main()
