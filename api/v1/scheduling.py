from fastapi import APIRouter, Depends, HTTPException, Query
from api.deps import get_current_tenant
from db.supabase import get_supabase_client
from typing import Optional
from datetime import date as date_type
from pydantic import BaseModel

from services.scheduling_service import SchedulingService
from services.i18n import DEFAULT_LANGUAGE, t

router = APIRouter(prefix="/appointments")


class CancelAppointmentRequest(BaseModel):
    reason: Optional[str] = None


@router.get("/available-slots")
async def get_available_slots(
    item_id: str = Query(...),
    date: str = Query(..., description="Fecha en formato AAAA-MM-DD"),
    tenant: dict = Depends(get_current_tenant),
):
    """Disponibilidad en tiempo real para un servicio en una fecha dada."""
    try:
        target_date = date_type.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Fecha inválida, usa el formato AAAA-MM-DD")

    service = SchedulingService()
    slots = await service.get_available_slots(tenant["id"], item_id, target_date)

    return {"slots": [slot.isoformat() for slot in slots]}


@router.get("")
async def list_appointments(
    tenant: dict = Depends(get_current_tenant),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
):
    """Listar citas del tenant."""
    db = get_supabase_client()

    query = db.table("appointments").select("*").eq("tenant_id", tenant["id"])

    if status:
        query = query.eq("status", status)

    query = query.order("scheduled_at", desc=False).limit(limit)
    result = query.execute()

    return result.data or []


@router.put("/{appointment_id}/cancel")
async def cancel_appointment(
    appointment_id: str,
    data: CancelAppointmentRequest,
    tenant: dict = Depends(get_current_tenant),
):
    """Cancelar una cita, respetando la política de cancelación del tenant."""
    service = SchedulingService()
    outcome = await service.cancel_appointment(tenant["id"], appointment_id, data.reason)

    # This endpoint is part of the seller-facing dashboard, so the message is
    # rendered in the default language rather than a customer's.
    message = t(outcome["message_key"], DEFAULT_LANGUAGE, **outcome.get("message_params", {}))

    if not outcome["success"]:
        raise HTTPException(status_code=400, detail=message)

    return {"message": message}
