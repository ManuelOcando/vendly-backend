#!/usr/bin/env python3
"""
Send the automated daily report to every tenant with analytics enabled
(spec requirement 21.1).

This script is intentionally NOT wired into any scheduled execution yet -
same "designed to run standalone, never deployed" shape as
services/alert_scheduler.py and scripts/send_appointment_reminders.py.
Only the daily report (requirement 21.1) is covered here; weekly reports
(21.2) and report customization (21.5) are out of scope for this pass -
AdvancedAnalyticsService.generate_weekly_report exists and can be pulled
on-demand via GET /api/v1/analytics/weekly-report, just not sent automatically.

To actually send daily reports on a schedule, wire this up as ONE of:
  - A Render Cron Job service running: python -m scripts.send_daily_reports
    once a day (e.g. at 22:00 local time, after most of the day's sales).
  - An in-process APScheduler loop started from main.py's startup event.

Until then, run it manually to send today's report to every eligible tenant:
    python -m scripts.send_daily_reports
"""
import sys
import asyncio
from pathlib import Path
import logging

sys.path.append(str(Path(__file__).parent.parent))

from db.supabase import get_supabase_client
from db.whatsapp_config import fetch_config
from services.advanced_analytics_service import AdvancedAnalyticsService
from services.whatsapp.meta_service import MetaWhatsAppService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def send_all_daily_reports() -> int:
    """Sends the daily report to every active tenant with the 'analytics'
    feature enabled. Returns the number of reports sent."""
    db = get_supabase_client()
    service = AdvancedAnalyticsService(db=db)
    sent_count = 0

    try:
        subscriptions_result = db.table("tenant_subscriptions").select(
            "tenant_id, features"
        ).eq("status", "active").execute()
    except Exception as e:
        logger.error(f"Error fetching active tenant subscriptions: {e}")
        return 0

    for subscription in subscriptions_result.data or []:
        tenant_id = subscription["tenant_id"]
        features = subscription.get("features") or {}
        if not features.get("analytics", False):
            continue

        try:
            if await _send_report_to_tenant(db, service, tenant_id):
                sent_count += 1
        except Exception as e:
            logger.error(f"Error sending daily report for tenant {tenant_id}: {e}")

    return sent_count


async def _send_report_to_tenant(db, service: AdvancedAnalyticsService, tenant_id: str) -> bool:
    config = fetch_config(
        db, tenant_id, "seller_phone, phone_number, phone_number_id, access_token"
    )

    if not config:
        logger.warning(f"No whatsapp_configs for tenant {tenant_id}, skipping daily report")
        return False

    seller_phone = config.get("seller_phone") or config.get("phone_number")
    if not seller_phone:
        logger.warning(f"No seller phone configured for tenant {tenant_id}, skipping daily report")
        return False

    report = await service.generate_daily_report(tenant_id)

    MetaWhatsAppService(
        phone_number_id=config["phone_number_id"],
        access_token=config["access_token"],
    ).send_message(seller_phone, report)
    return True


if __name__ == "__main__":
    count = asyncio.run(send_all_daily_reports())
    logger.info(f"Sent {count} daily report(s)")
