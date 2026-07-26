"""
Service scheduling handler: appointment booking flow for professional-
services tenants (spec requirement 20). External calendar sync (req 20.5) is
out of scope - internal scheduling only.

Multi-step flow driven by session_data["scheduling"] (not `current_state` sub-
values - the conversation_sessions.current_state CHECK constraint only needs
to move to the single already-reserved 'scheduling_service' value; the
individual step is tracked inside the JSONB session_data instead).
"""
from typing import Dict, Any, Optional, List
from datetime import datetime, date, timedelta
import logging

from .base import BaseWhatsAppHandler
from services.scheduling_service import SchedulingService

logger = logging.getLogger(__name__)

BOOKING_TRIGGER_KEYWORDS = ["agendar", "reservar", "programar cita", "programar una cita", "cita"]
CANCEL_APPOINTMENT_KEYWORDS = ["cancelar mi cita"]


def _parse_date(text: str) -> Optional[date]:
    text = text.strip().lower()
    if text in ("hoy",):
        return date.today()
    if text in ("mañana", "manana"):
        return date.today() + timedelta(days=1)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


class ServiceSchedulingHandler(BaseWhatsAppHandler):
    """Drives the multi-step appointment booking conversation"""

    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        message = message_data.get("message", "").lower().strip()
        session = message_data.get("session", {})

        if session.get("current_state") == "scheduling_service":
            return True

        if any(keyword in message for keyword in CANCEL_APPOINTMENT_KEYWORDS):
            return True

        return any(keyword in message for keyword in BOOKING_TRIGGER_KEYWORDS)

    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        tenant_id = message_data.get("tenant_id")
        phone = message_data.get("phone", "")
        message = message_data.get("message", "").strip()
        message_lower = message.lower()
        session = message_data.get("session", {})
        session_data = dict(session.get("session_data") or {})
        session_id = session.get("id")

        service = SchedulingService(db=self.db)

        try:
            if any(keyword in message_lower for keyword in CANCEL_APPOINTMENT_KEYWORDS):
                return await self._handle_cancellation(service, tenant_id, phone)

            scheduling = session_data.get("scheduling")

            if not scheduling:
                return await self._start_booking(tenant_id, session_id, session_data)

            step = scheduling.get("step")
            if step == "selecting_service":
                return await self._select_service(tenant_id, message, session_id, session_data, scheduling)
            if step == "selecting_date":
                return await self._select_date(service, tenant_id, message, session_id, session_data, scheduling)
            if step == "selecting_time":
                return await self._select_time(message, session_id, session_data, scheduling)
            if step == "confirming":
                return await self._confirm_booking(service, tenant_id, phone, message, session_id, session_data, scheduling)

            # Unknown step - reset
            await self._reset_flow(session_id, session_data)
            return "Vamos a empezar de nuevo. " + await self._start_booking(tenant_id, session_id, session_data)
        except Exception as e:
            logger.error(f"Error in ServiceSchedulingHandler: {e}")
            await self._reset_flow(session_id, session_data)
            return "Ocurrió un error al agendar tu cita. Por favor intenta nuevamente."

    async def _start_booking(
        self, tenant_id: str, session_id: Optional[str], session_data: Dict[str, Any]
    ) -> str:
        services = await self._get_bookable_services(tenant_id)
        if not services:
            return "No ofrecemos servicios agendables por el momento."

        lines = [f"{i + 1}. {item['name']}" for i, item in enumerate(services)]
        session_data["scheduling"] = {
            "step": "selecting_service",
            "services": [{"id": item["id"], "name": item["name"]} for item in services],
        }
        if session_id:
            await self.update_session_state(session_id, "scheduling_service", session_data)

        return "¿Qué servicio te gustaría agendar?\n" + "\n".join(lines)

    async def _get_bookable_services(self, tenant_id: str) -> List[Dict[str, Any]]:
        try:
            result = self.db.table("items").select("id, name").eq(
                "tenant_id", tenant_id
            ).eq("type", "service").eq("is_active", True).limit(10).execute()
            return result.data or []
        except Exception as e:
            logger.warning(f"Error getting bookable services for tenant {tenant_id}: {e}")
            return []

    async def _select_service(
        self, tenant_id: str, message: str, session_id: Optional[str],
        session_data: Dict[str, Any], scheduling: Dict[str, Any],
    ) -> str:
        services = scheduling.get("services", [])
        choice = self._parse_choice(message, len(services))
        if choice is None:
            return "Por favor responde con el número del servicio que quieres agendar."

        selected = services[choice]
        scheduling["item_id"] = selected["id"]
        scheduling["item_name"] = selected["name"]
        scheduling["step"] = "selecting_date"
        session_data["scheduling"] = scheduling
        if session_id:
            await self.update_session_state(session_id, "scheduling_service", session_data)

        return (
            f"Elegiste: {selected['name']}.\n"
            "¿Qué día te gustaría? Puedes responder 'hoy', 'mañana', o una fecha (DD/MM/AAAA)."
        )

    async def _select_date(
        self, service: SchedulingService, tenant_id: str, message: str,
        session_id: Optional[str], session_data: Dict[str, Any], scheduling: Dict[str, Any],
    ) -> str:
        target_date = _parse_date(message)
        if not target_date:
            return "No entendí la fecha. Responde 'hoy', 'mañana', o en formato DD/MM/AAAA."

        slots = await service.get_available_slots(tenant_id, scheduling["item_id"], target_date)
        if not slots:
            return "No hay disponibilidad ese día. ¿Quieres intentar con otra fecha?"

        slots = slots[:8]
        lines = [f"{i + 1}. {slot.strftime('%H:%M')}" for i, slot in enumerate(slots)]
        scheduling["date"] = target_date.isoformat()
        scheduling["slots"] = [slot.isoformat() for slot in slots]
        scheduling["step"] = "selecting_time"
        session_data["scheduling"] = scheduling
        if session_id:
            await self.update_session_state(session_id, "scheduling_service", session_data)

        return f"Horarios disponibles para el {target_date.strftime('%d/%m/%Y')}:\n" + "\n".join(lines)

    async def _select_time(
        self, message: str, session_id: Optional[str],
        session_data: Dict[str, Any], scheduling: Dict[str, Any],
    ) -> str:
        slots = scheduling.get("slots", [])
        choice = self._parse_choice(message, len(slots))
        if choice is None:
            return "Por favor responde con el número del horario que prefieres."

        scheduling["selected_slot"] = slots[choice]
        scheduling["step"] = "confirming"
        session_data["scheduling"] = scheduling
        if session_id:
            await self.update_session_state(session_id, "scheduling_service", session_data)

        slot_dt = datetime.fromisoformat(slots[choice])
        return (
            f"Confirmas tu cita para {scheduling['item_name']} el "
            f"{slot_dt.strftime('%d/%m/%Y a las %H:%M')}? Responde sí o no."
        )

    async def _confirm_booking(
        self, service: SchedulingService, tenant_id: str, phone: str, message: str,
        session_id: Optional[str], session_data: Dict[str, Any], scheduling: Dict[str, Any],
    ) -> str:
        message_lower = message.lower().strip()
        if message_lower not in ("sí", "si", "confirmo", "confirmar"):
            await self._reset_flow(session_id, session_data)
            return "Cita cancelada. Escríbeme si quieres agendar de nuevo."

        scheduled_at = datetime.fromisoformat(scheduling["selected_slot"])
        appointment = await service.create_appointment(
            tenant_id, phone, scheduling["item_id"], scheduled_at
        )
        await self._reset_flow(session_id, session_data)

        if not appointment:
            return "Ese horario ya no está disponible. Por favor intenta agendar de nuevo."

        return (
            f"✅ ¡Cita confirmada! {scheduling['item_name']} el "
            f"{scheduled_at.strftime('%d/%m/%Y a las %H:%M')}. Te enviaremos recordatorios antes de tu cita."
        )

    async def _handle_cancellation(self, service: SchedulingService, tenant_id: str, phone: str) -> str:
        try:
            result = self.db.table("appointments").select("*").eq(
                "tenant_id", tenant_id
            ).eq("customer_phone", phone).eq("status", "scheduled").order(
                "scheduled_at", desc=False
            ).limit(1).execute()
        except Exception as e:
            logger.error(f"Error looking up appointment to cancel for {phone}: {e}")
            return "Ocurrió un error al buscar tu cita."

        if not result.data:
            return "No encontré ninguna cita programada a tu nombre."

        appointment = result.data[0]
        outcome = await service.cancel_appointment(tenant_id, appointment["id"])
        return outcome["message"]

    async def _reset_flow(self, session_id: Optional[str], session_data: Dict[str, Any]) -> None:
        session_data.pop("scheduling", None)
        if session_id:
            await self.update_session_state(session_id, "initial", session_data)

    def _parse_choice(self, message: str, max_options: int) -> Optional[int]:
        stripped = message.strip()
        if not stripped.isdigit():
            return None
        index = int(stripped) - 1
        if 0 <= index < max_options:
            return index
        return None
