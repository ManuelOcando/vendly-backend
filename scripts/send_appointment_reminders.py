#!/usr/bin/env python3
"""
Send 24h/1h appointment reminders (spec requirement 20.3).

This script is intentionally NOT wired into any scheduled execution yet -
per product decision, only the reminder *logic* was built this pass, not the
infrastructure to run it on a timer (there is none in this project today;
see services/alert_scheduler.py, which has the same "designed to run
standalone, never deployed" shape for the smart-alerts feature).

To actually send reminders on time, wire this up as ONE of:
  - A Render Cron Job service running: python -m scripts.send_appointment_reminders
    (run it every ~15 minutes; the 24h/1h windows in
    SchedulingService.get_reminders_due have slop built in so a 15-minute
    cadence won't miss anyone)
  - An in-process APScheduler loop started from main.py's startup event,
    calling send_due_reminders() on the same cadence.

Until then, run it manually to send whatever reminders are currently due:
    python -m scripts.send_appointment_reminders
"""
import sys
import asyncio
from pathlib import Path
import logging

sys.path.append(str(Path(__file__).parent.parent))

from db.supabase import get_supabase_client
from db.whatsapp_config import fetch_config
from services.scheduling_service import SchedulingService
from services.whatsapp.meta_service import MetaWhatsAppService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def send_due_reminders() -> int:
    """Sends every 24h/1h reminder currently due, across all tenants.
    Returns the number of reminders sent."""
    db = get_supabase_client()
    service = SchedulingService(db=db)
    sent_count = 0

    for kind in ("24h", "1h"):
        due = await service.get_reminders_due(kind)
        for appointment in due:
            if await _send_reminder(db, appointment, kind):
                await service.mark_reminder_sent(appointment["id"], kind)
                sent_count += 1

    return sent_count


async def _send_reminder(db, appointment: dict, kind: str) -> bool:
    tenant_id = appointment["tenant_id"]
    customer_phone = appointment["customer_phone"]

    try:
        config = fetch_config(db, tenant_id, "phone_number_id, access_token")

        if not config:
            logger.warning(f"No whatsapp_configs for tenant {tenant_id}, skipping reminder")
            return False

        item_result = db.table("items").select("name").eq(
            "id", appointment["item_id"]
        ).execute()
        item_name = item_result.data[0]["name"] if item_result.data else "tu cita"

        from datetime import datetime
        scheduled_at = datetime.fromisoformat(appointment["scheduled_at"])
        when = "mañana" if kind == "24h" else "en 1 hora"
        message = (
            f"⏰ Recordatorio: tienes una cita para {item_name} {when} "
            f"({scheduled_at.strftime('%d/%m/%Y a las %H:%M')})."
        )

        MetaWhatsAppService(
            phone_number_id=config["phone_number_id"],
            access_token=config["access_token"],
        ).send_message(customer_phone, message)
        return True
    except Exception as e:
        logger.error(f"Error sending {kind} reminder for appointment {appointment.get('id')}: {e}")
        return False


if __name__ == "__main__":
    count = asyncio.run(send_due_reminders())
    logger.info(f"Sent {count} appointment reminder(s)")
