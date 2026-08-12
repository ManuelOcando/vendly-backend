"""
La unica puerta a la tabla whatsapp_configs.

Existe por una razon concreta: access_token se guarda cifrado, y habia 15
sitios repartidos en 11 archivos que lo leian directamente. Cifrar dejandolos
ahi obliga a acordarse de descifrar en cada uno, y el siguiente que alguien
escriba se olvidara. Aqui el descifrado ocurre una vez, donde no se puede
saltar.

Ojo con como se cuentan esos sitios: buscar "access_token" no los encuentra
todos. Varios hacian select("*"), que arrastra el token sin nombrarlo, y uno de
ellos -- el aviso al vendedor por cada pedido nuevo, en
services/whatsapp/handlers/customer.py -- si lo usaba para enviar. Habria
mandado el texto cifrado a Meta.

tests/test_token_crypto.py monta guardia: ningun modulo fuera de este puede
seleccionar access_token ni "*" de esta tabla.

Este modulo no importa nada de services/ a proposito. services/__init__.py
carga el orquestador al importarse, y el orquestador usa upsert_seller_phone de
aqui: cualquier import hacia services cierra el ciclo. Por eso db/token_crypto.py
vive en db/ y no junto al resto del codigo de WhatsApp.
"""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from db.token_crypto import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)

TABLE = "whatsapp_configs"


def fetch_config(db, tenant_id: str, columns: str = "*") -> Optional[Dict[str, Any]]:
    """
    La fila de este tenant, con access_token ya descifrado, o None si no hay.

    `columns` se mantiene porque los llamantes piden juegos distintos
    (seller_phone, phone_number, phone_number_id...) y no tiene sentido
    traer la fila entera para leer dos campos.

    No captura excepciones: los llamantes ya tienen su try/except con el
    mensaje que le sirve a cada uno.
    """
    result = db.table(TABLE).select(columns).eq("tenant_id", tenant_id).limit(1).execute()

    if not result.data:
        return None

    config = dict(result.data[0])
    if config.get("access_token"):
        config["access_token"] = decrypt_token(config["access_token"])
    return config


def save_config(db, tenant_id: str, config: Dict[str, Any]) -> None:
    """
    Inserta o actualiza la fila del tenant, cifrando el token si viene.

    Lanza TokenEncryptionUnavailable si hay token pero no hay clave. Es
    deliberado: preferimos que guardar falle a guardar en claro creyendo que
    ciframos.
    """
    payload = dict(config)
    if payload.get("access_token"):
        payload["access_token"] = encrypt_token(payload["access_token"])

    existing = db.table(TABLE).select("id").eq("tenant_id", tenant_id).execute()

    if existing and existing.data:
        db.table(TABLE).update(payload).eq("tenant_id", tenant_id).execute()
        logger.info("whatsapp_configs actualizado para tenant %s", tenant_id)
    else:
        payload.setdefault("tenant_id", tenant_id)
        payload.setdefault("created_at", datetime.now().isoformat())
        db.table(TABLE).insert(payload).execute()
        logger.info("whatsapp_configs creado para tenant %s", tenant_id)


def find_tenant_id_by_phone_number_id(db, phone_number_id: str) -> Optional[str]:
    """
    De que tenant es este numero de Meta. Lo usa el webhook para enrutar.

    No lee credenciales, pero vive aqui igual: si la tabla se consulta desde
    fuera aunque sea para esto, el guardia de tests deja de poder ser estricto
    y vuelve a colarse una lectura del token sin descifrar.
    """
    result = db.table(TABLE).select("tenant_id, phone_number_id").eq(
        "phone_number_id", phone_number_id
    ).execute()

    if not result.data:
        return None
    return result.data[0]["tenant_id"]


def delete_config(db, tenant_id: str) -> None:
    """Borra la configuracion del tenant."""
    db.table(TABLE).delete().eq("tenant_id", tenant_id).execute()


def upsert_seller_phone(db, tenant_id: str, seller_phone: str) -> None:
    """
    Guarda el telefono del vendedor durante el onboarding, creando la fila si
    hace falta.

    phone_number_id y access_token son NOT NULL sin default, asi que la fila
    placeholder tiene que traerlos vacios. Ese es el unico motivo por el que
    esta funcion vive aqui y no en el orquestador: para que el nombre de la
    columna no aparezca fuera de este modulo.
    """
    existing = db.table(TABLE).select("id").eq("tenant_id", tenant_id).execute()

    if existing.data:
        db.table(TABLE).update({"seller_phone": seller_phone}).eq(
            "tenant_id", tenant_id
        ).execute()
    else:
        db.table(TABLE).insert({
            "tenant_id": tenant_id,
            "seller_phone": seller_phone,
            "phone_number_id": "",
            "access_token": "",
        }).execute()
