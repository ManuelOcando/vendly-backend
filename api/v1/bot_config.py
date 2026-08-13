"""
Configuracion del bot: por ahora, los datos de cobro del vendedor.

Modulo propio y no dentro de whatsapp.py porque esto no son credenciales de
Meta, sino como se comporta el bot. Los otros mensajes que ya tiene la tabla
(bienvenida, fuera de horario, confirmacion) caen aqui cuando les toque.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_current_tenant
from db.supabase import get_supabase_client
from services.i18n import DEFAULT_LANGUAGE, t
from services.payment_instructions import compose, tiene_datos

router = APIRouter(prefix="/bot-config")
logger = logging.getLogger(__name__)

TABLE = "bot_configurations"

# Suficiente para unos datos bancarios y unas notas, y corto de sobra para que
# nadie use esto como almacen de texto.
LARGO_CAMPO = 120
LARGO_NOTAS = 500


class PaymentInfo(BaseModel):
    """Los datos de cobro tal cual los escribe el vendedor en el formulario."""

    bank: str = Field("", max_length=LARGO_CAMPO)
    id_number: str = Field("", max_length=LARGO_CAMPO)
    phone: str = Field("", max_length=LARGO_CAMPO)
    # Texto libre, y es lo que cubre a quien no cobra por pago movil: efectivo
    # contra entrega, Zelle, Binance, o varias cosas a la vez.
    notes: str = Field("", max_length=LARGO_NOTAS)

    def limpio(self) -> dict:
        return {k: (v or "").strip() for k, v in self.model_dump().items()}


class BotConfigUpdate(BaseModel):
    payment_info: PaymentInfo


@router.get("")
async def get_bot_config(tenant: dict = Depends(get_current_tenant)):
    """
    La configuracion del bot de este tenant.

    No crea la fila si no existe: un GET no debe escribir. Devuelve los campos
    vacios y una vista previa con el texto que el cliente recibe hoy.
    """
    db = get_supabase_client()

    result = db.table(TABLE).select("payment_info, payment_instructions").eq(
        "tenant_id", tenant["id"]
    ).limit(1).execute()

    fila = result.data[0] if result.data else {}
    info = fila.get("payment_info") or {}

    return {
        "payment_info": PaymentInfo(**{
            k: str(info.get(k) or "") for k in PaymentInfo.model_fields
        }).model_dump(),
        "configured": tiene_datos(info),
        # Lo que se le manda al cliente ahora mismo, para que el vendedor lo vea
        # antes de que lo vea nadie mas.
        "preview": compose(
            info, 0.0, DEFAULT_LANGUAGE,
            legacy_text=fila.get("payment_instructions"),
        ),
    }


@router.put("")
async def update_bot_config(
    data: BotConfigUpdate,
    tenant: dict = Depends(get_current_tenant),
):
    """
    Guarda los datos de cobro, creando la fila si no la habia.

    payment_instructions se fija siempre, aunque sea a cadena vacia. Es
    deliberado: esa columna tenia como DEFAULT en la base un texto con
    marcadores sin sustituir ({bank}, {ci}, {phone}) que nadie rellena, asi que
    una fila insertada sin ese campo le mandaria las llaves literales al
    cliente. La migracion 023 quita el default; esto lo cubre igualmente para
    las bases que no la tengan aplicada todavia.
    """
    db = get_supabase_client()
    info = data.payment_info.limpio()

    payload = {
        "payment_info": info,
        "payment_instructions": "",
        "tenant_id": tenant["id"],
    }

    try:
        existente = db.table(TABLE).select("id").eq(
            "tenant_id", tenant["id"]
        ).limit(1).execute()

        if existente.data:
            payload.pop("tenant_id")
            db.table(TABLE).update(payload).eq("tenant_id", tenant["id"]).execute()
        else:
            db.table(TABLE).insert(payload).execute()
    except Exception as e:
        logger.error(
            "No se pudo guardar la configuracion del bot del tenant %s: %s",
            tenant["id"], e, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="No se pudo guardar la configuración.")

    return {
        "status": "ok",
        "configured": tiene_datos(info),
        "preview": compose(info, 0.0, DEFAULT_LANGUAGE),
    }
