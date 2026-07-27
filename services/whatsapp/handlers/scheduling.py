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
from services.i18n import DEFAULT_LANGUAGE, matches_exact_intent, matches_intent, t

logger = logging.getLogger(__name__)


def _parse_date(text: str) -> Optional[date]:
    """Parse a relative or explicit date, in any supported language."""
    text = text.strip().lower()
    if matches_exact_intent(text, "today"):
        return date.today()
    if matches_exact_intent(text, "tomorrow"):
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

        if matches_intent(message, "cancel_appointment"):
            return True

        return matches_intent(message, "booking")

    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        tenant_id = message_data.get("tenant_id")
        phone = message_data.get("phone", "")
        message = message_data.get("message", "").strip()
        message_lower = message.lower()
        session = message_data.get("session", {})
        session_data = dict(session.get("session_data") or {})
        session_id = session.get("id")
        language = message_data.get("language", DEFAULT_LANGUAGE)

        service = SchedulingService(db=self.db)

        try:
            if matches_intent(message_lower, "cancel_appointment"):
                return await self._handle_cancellation(service, tenant_id, phone, language)

            scheduling = session_data.get("scheduling")

            if not scheduling:
                return await self._start_booking(tenant_id, session_id, session_data, language)

            step = scheduling.get("step")
            if step == "selecting_service":
                return await self._select_service(tenant_id, message, session_id, session_data, scheduling, language)
            if step == "selecting_date":
                return await self._select_date(service, tenant_id, message, session_id, session_data, scheduling, language)
            if step == "selecting_time":
                return await self._select_time(message, session_id, session_data, scheduling, language)
            if step == "confirming":
                return await self._confirm_booking(service, tenant_id, phone, message, session_id, session_data, scheduling, language)

            # Unknown step - reset
            await self._reset_flow(session_id, session_data)
            return t("scheduling.restart", language) + await self._start_booking(
                tenant_id, session_id, session_data, language
            )
        except Exception as e:
            logger.error(f"Error in ServiceSchedulingHandler: {e}")
            await self._reset_flow(session_id, session_data)
            return t("scheduling.error", language)

    async def _start_booking(
        self, tenant_id: str, session_id: Optional[str], session_data: Dict[str, Any],
        language: str = DEFAULT_LANGUAGE
    ) -> str:
        services = await self._get_bookable_services(tenant_id)
        if not services:
            return t("scheduling.no_services", language)

        lines = [f"{i + 1}. {item['name']}" for i, item in enumerate(services)]
        session_data["scheduling"] = {
            "step": "selecting_service",
            "services": [{"id": item["id"], "name": item["name"]} for item in services],
        }
        if session_id:
            await self.update_session_state(session_id, "scheduling_service", session_data)

        return t("scheduling.which_service", language, options="\n".join(lines))

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
        language: str = DEFAULT_LANGUAGE,
    ) -> str:
        services = scheduling.get("services", [])
        choice = self._parse_choice(message, len(services))
        if choice is None:
            return t("scheduling.choose_service_number", language)

        selected = services[choice]
        scheduling["item_id"] = selected["id"]
        scheduling["item_name"] = selected["name"]
        scheduling["step"] = "selecting_date"
        session_data["scheduling"] = scheduling
        if session_id:
            await self.update_session_state(session_id, "scheduling_service", session_data)

        return t("scheduling.service_chosen", language, service=selected["name"])

    async def _select_date(
        self, service: SchedulingService, tenant_id: str, message: str,
        session_id: Optional[str], session_data: Dict[str, Any], scheduling: Dict[str, Any],
        language: str = DEFAULT_LANGUAGE,
    ) -> str:
        target_date = _parse_date(message)
        if not target_date:
            return t("scheduling.date_not_understood", language)

        slots = await service.get_available_slots(tenant_id, scheduling["item_id"], target_date)
        if not slots:
            return t("scheduling.no_availability", language)

        slots = slots[:8]
        lines = [f"{i + 1}. {slot.strftime('%H:%M')}" for i, slot in enumerate(slots)]
        scheduling["date"] = target_date.isoformat()
        scheduling["slots"] = [slot.isoformat() for slot in slots]
        scheduling["step"] = "selecting_time"
        session_data["scheduling"] = scheduling
        if session_id:
            await self.update_session_state(session_id, "scheduling_service", session_data)

        return t(
            "scheduling.available_times", language,
            date=target_date.strftime("%d/%m/%Y"), options="\n".join(lines),
        )

    async def _select_time(
        self, message: str, session_id: Optional[str],
        session_data: Dict[str, Any], scheduling: Dict[str, Any],
        language: str = DEFAULT_LANGUAGE,
    ) -> str:
        slots = scheduling.get("slots", [])
        choice = self._parse_choice(message, len(slots))
        if choice is None:
            return t("scheduling.choose_time_number", language)

        scheduling["selected_slot"] = slots[choice]
        scheduling["step"] = "confirming"
        session_data["scheduling"] = scheduling
        if session_id:
            await self.update_session_state(session_id, "scheduling_service", session_data)

        slot_dt = datetime.fromisoformat(slots[choice])
        return t(
            "scheduling.confirm_prompt", language,
            service=scheduling["item_name"],
            datetime=slot_dt.strftime("%d/%m/%Y %H:%M"),
        )

    async def _confirm_booking(
        self, service: SchedulingService, tenant_id: str, phone: str, message: str,
        session_id: Optional[str], session_data: Dict[str, Any], scheduling: Dict[str, Any],
        language: str = DEFAULT_LANGUAGE,
    ) -> str:
        if not matches_exact_intent(message, "confirm"):
            await self._reset_flow(session_id, session_data)
            return t("scheduling.cancelled", language)

        scheduled_at = datetime.fromisoformat(scheduling["selected_slot"])
        appointment = await service.create_appointment(
            tenant_id, phone, scheduling["item_id"], scheduled_at
        )
        await self._reset_flow(session_id, session_data)

        if not appointment:
            return t("scheduling.slot_taken", language)

        return t(
            "scheduling.confirmed", language,
            service=scheduling["item_name"],
            datetime=scheduled_at.strftime("%d/%m/%Y %H:%M"),
        )

    async def _handle_cancellation(
        self, service: SchedulingService, tenant_id: str, phone: str,
        language: str = DEFAULT_LANGUAGE
    ) -> str:
        try:
            result = self.db.table("appointments").select("*").eq(
                "tenant_id", tenant_id
            ).eq("customer_phone", phone).eq("status", "scheduled").order(
                "scheduled_at", desc=False
            ).limit(1).execute()
        except Exception as e:
            logger.error(f"Error looking up appointment to cancel for {phone}: {e}")
            return t("scheduling.lookup_error", language)

        if not result.data:
            return t("scheduling.no_appointment", language)

        appointment = result.data[0]
        outcome = await service.cancel_appointment(tenant_id, appointment["id"])
        return t(outcome["message_key"], language, **outcome.get("message_params", {}))

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
