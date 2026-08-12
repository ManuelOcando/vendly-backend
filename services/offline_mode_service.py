"""
Intelligent Offline Mode service (spec requirement 14).

Detects when the bot should stop responding normally to customers - either
because the seller manually paused it, configured business hours that don't
cover the current time, marked today as a holiday exception, or has been
inactive for a while - stores whatever customers write during that window,
and lets the seller know about it once they're back.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, date, time, timedelta, timezone
import re
import logging

from db.supabase import get_supabase_client
from db.whatsapp_config import fetch_config
from services.whatsapp.meta_service import MetaWhatsAppService
from services.i18n import DEFAULT_LANGUAGE, t

logger = logging.getLogger(__name__)

INACTIVITY_THRESHOLD_HOURS = 48
DEFAULT_TIMEZONE = "America/Caracas"

WEEKDAY_KEYS = [
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
]

# Order matters: multi-day patterns must be checked before the single-day
# patterns they contain (e.g. "lunes a viernes" before "lunes"), since we
# stop at the first substring match - same approach as
# onboarding.py::_parse_business_hours.
DAY_PATTERNS = {
    "lunes a viernes": ["monday", "tuesday", "wednesday", "thursday", "friday"],
    "lunes-viernes": ["monday", "tuesday", "wednesday", "thursday", "friday"],
    "lunes a sábado": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"],
    "lunes a sabado": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"],
    "sábado": ["saturday"],
    "sabado": ["saturday"],
    "domingo": ["sunday"],
    "lunes": ["monday"],
    "martes": ["tuesday"],
    "miércoles": ["wednesday"],
    "miercoles": ["wednesday"],
    "jueves": ["thursday"],
    "viernes": ["friday"],
}

TIME_PATTERN = re.compile(
    r'(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)\s*(?:-|a)?\s*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)'
)


def _normalize_time(raw: str) -> Optional[str]:
    """Normalize a time string (24h '9:00' or 12h '11:00 AM') to 24h 'HH:MM'."""
    raw = raw.strip()
    for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
        try:
            return datetime.strptime(raw.upper(), fmt).strftime("%H:%M")
        except ValueError:
            continue
    return None


def parse_weekly_schedule(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse free-text weekly business hours into
    {day: {"closed": True}} or {day: {"open": "HH:MM", "close": "HH:MM"}}.

    Only returns the days actually mentioned in `text` - the caller decides
    whether missing days should be left untouched (single-day correction) or
    treated as closed (full-week reconfiguration). Supports both 24h and
    12h AM/PM times, dash- or space-separated, and the keyword "cerrado".
    """
    days: Dict[str, Dict[str, Any]] = {}

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        line_lower = line.lower()
        matched_days = None
        for day_key, weekdays in DAY_PATTERNS.items():
            if day_key in line_lower:
                matched_days = weekdays
                break

        if not matched_days:
            continue

        if "cerrado" in line_lower:
            for day in matched_days:
                days[day] = {"closed": True}
            continue

        time_match = TIME_PATTERN.search(line)
        if not time_match:
            continue

        open_time = _normalize_time(time_match.group(1))
        close_time = _normalize_time(time_match.group(2))
        if not open_time or not close_time:
            continue

        for day in matched_days:
            days[day] = {"open": open_time, "close": close_time}

    return days


class OfflineModeService:
    """Service for automatic/manual offline-mode detection and configuration"""

    def __init__(self, db=None):
        self.db = db or get_supabase_client()

    # ------------------------------------------------------------------
    # Reading state
    # ------------------------------------------------------------------

    async def _get_bot_config(self, tenant_id: str) -> Dict[str, Any]:
        try:
            result = self.db.table("bot_configurations").select("*").eq(
                "tenant_id", tenant_id
            ).limit(1).execute()
            return result.data[0] if result.data else {}
        except Exception as e:
            logger.error(f"Error fetching bot configuration for tenant {tenant_id}: {e}", exc_info=True)
            return {}

    async def _get_exception_for_date(
        self, tenant_id: str, target_date: date
    ) -> Optional[Dict[str, Any]]:
        try:
            result = self.db.table("business_hours_exceptions").select("*").eq(
                "tenant_id", tenant_id
            ).eq("exception_date", target_date.isoformat()).limit(1).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error fetching business hours exception for tenant {tenant_id}: {e}", exc_info=True)
            return None

    def _get_zone(self, tz_name: Optional[str]):
        from zoneinfo import ZoneInfo
        try:
            return ZoneInfo(tz_name or DEFAULT_TIMEZONE)
        except Exception as e:
            # A typo in a tenant's timezone silently shifts every opening hour,
            # reminder and appointment they have. Falling back is right; doing
            # it quietly is not.
            logger.error(
                "Unknown timezone %r, falling back to %s: %s",
                tz_name, DEFAULT_TIMEZONE, e, exc_info=True,
            )
            return ZoneInfo(DEFAULT_TIMEZONE)

    async def is_offline(self, tenant_id: str, now: Optional[datetime] = None) -> bool:
        """Whether the bot should currently treat customer messages as offline.

        Fail-open by design: a tenant that never configured anything (no
        `bot_configurations` row, or a day/field left unconfigured) is never
        considered offline, so existing tenants keep working exactly as
        before this feature existed.

        `now` (timezone-aware) can be injected for testing; defaults to the
        real current time.
        """
        config = await self._get_bot_config(tenant_id)
        if not config:
            return False

        if config.get("bot_paused"):
            return True

        if not config.get("auto_reply_enabled", True):
            return False

        now_utc = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
        zone = self._get_zone(config.get("timezone"))
        now_local = now_utc.astimezone(zone)
        today = now_local.date()

        exception = await self._get_exception_for_date(tenant_id, today)
        if exception is not None:
            if exception.get("is_closed"):
                return True
            open_str = exception.get("open_time")
            close_str = exception.get("close_time")
            if open_str and close_str:
                return not self._time_in_range(now_local.time(), open_str, close_str)
            return False

        last_activity = config.get("last_seller_activity_at")
        if last_activity:
            try:
                last_dt = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                if now_utc - last_dt > timedelta(hours=INACTIVITY_THRESHOLD_HOURS):
                    return True
            except (ValueError, AttributeError):
                pass

        business_hours = config.get("business_hours") or {}
        day_conf = business_hours.get(WEEKDAY_KEYS[today.weekday()])
        if not day_conf:
            return False
        if day_conf.get("closed"):
            return True
        open_str = day_conf.get("open")
        close_str = day_conf.get("close")
        if not open_str or not close_str:
            return False
        return not self._time_in_range(now_local.time(), open_str, close_str)

    def _time_in_range(self, current: time, open_str: str, close_str: str) -> bool:
        """Whether `current` falls inside an open/close window.

        Handles windows that cross midnight (a bar open 20:00-02:00): when
        close is not after open, the range wraps to the next day, so being
        past opening OR before closing counts as open. A plain
        `open <= current < close` would report such a business as closed
        around the clock.
        """
        try:
            open_t = datetime.strptime(open_str, "%H:%M").time()
            close_t = datetime.strptime(close_str, "%H:%M").time()
        except ValueError:
            return True

        if close_t <= open_t:
            return current >= open_t or current < close_t
        return open_t <= current < close_t

    async def get_offline_reply(self, tenant_id: str, language: str = DEFAULT_LANGUAGE) -> str:
        """The out-of-hours notice shown to a customer.

        A seller-authored `out_of_hours_message` wins and is sent verbatim -
        it's their own wording, in their own language. Only the built-in
        default is translated.
        """
        config = await self._get_bot_config(tenant_id)
        message = config.get("out_of_hours_message")
        if message:
            return message
        return t("offline.default_reply", language)

    # ------------------------------------------------------------------
    # Offline messages left by customers
    # ------------------------------------------------------------------

    async def store_offline_message(
        self, tenant_id: str, customer_phone: str, message: str
    ) -> None:
        try:
            self.db.table("offline_messages").insert({
                "tenant_id": tenant_id,
                "customer_phone": customer_phone,
                "message": message,
            }).execute()
        except Exception as e:
            logger.error(f"Could not store offline message for tenant {tenant_id}: {e}", exc_info=True)

    async def record_seller_activity(self, tenant_id: str) -> None:
        await self._upsert_bot_config(tenant_id, {
            "last_seller_activity_at": datetime.now(timezone.utc).isoformat()
        })

    async def notify_seller_of_pending_messages(self, tenant_id: str) -> None:
        """Best-effort: summarize and send any offline messages left by
        customers since the seller was last notified, then mark them sent.
        Mirrors PostSaleService._notify_seller - never raises."""
        try:
            pending = self.db.table("offline_messages").select("*").eq(
                "tenant_id", tenant_id
            ).is_("notified_at", "null").order("created_at").execute()

            messages = pending.data if pending.data else []
            if not messages:
                return

            config = fetch_config(
                self.db, tenant_id,
                "seller_phone, phone_number, phone_number_id, access_token",
            )

            if not config:
                return
            seller_phone = config.get("seller_phone") or config.get("phone_number")
            if not seller_phone:
                return

            lines = [f"📬 Tenés {len(messages)} mensaje(s) de cuando estuviste offline:"]
            for m in messages[:10]:
                lines.append(f"• {m['customer_phone']}: {m['message']}")
            if len(messages) > 10:
                lines.append(f"...y {len(messages) - 10} más.")

            MetaWhatsAppService(
                phone_number_id=config["phone_number_id"],
                access_token=config["access_token"],
            ).send_message(seller_phone, "\n".join(lines))

            self.db.table("offline_messages").update({
                "notified_at": datetime.now(timezone.utc).isoformat()
            }).in_("id", [m["id"] for m in messages]).execute()
        except Exception as e:
            logger.error(f"Could not notify seller of pending offline messages for tenant {tenant_id}: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Seller configuration
    # ------------------------------------------------------------------

    async def _upsert_bot_config(self, tenant_id: str, fields: Dict[str, Any]) -> bool:
        try:
            existing = self.db.table("bot_configurations").select("id").eq(
                "tenant_id", tenant_id
            ).limit(1).execute()

            if existing.data:
                self.db.table("bot_configurations").update(fields).eq(
                    "tenant_id", tenant_id
                ).execute()
            else:
                self.db.table("bot_configurations").insert({
                    "tenant_id": tenant_id,
                    **fields,
                }).execute()
            return True
        except Exception as e:
            logger.error(f"Error updating bot configuration for tenant {tenant_id}: {e}")
            return False

    async def set_business_hours(
        self, tenant_id: str, parsed_days: Dict[str, Dict[str, Any]], replace_week: bool
    ) -> bool:
        if not parsed_days:
            return False

        config = await self._get_bot_config(tenant_id)
        current = dict(config.get("business_hours") or {})

        if replace_week:
            new_hours = {day: {"closed": True} for day in WEEKDAY_KEYS}
            new_hours.update(parsed_days)
        else:
            new_hours = current
            new_hours.update(parsed_days)

        return await self._upsert_bot_config(tenant_id, {"business_hours": new_hours})

    async def set_date_exception(
        self,
        tenant_id: str,
        exception_date: date,
        is_closed: bool,
        open_time: Optional[str] = None,
        close_time: Optional[str] = None,
    ) -> bool:
        try:
            row = {
                "tenant_id": tenant_id,
                "exception_date": exception_date.isoformat(),
                "is_closed": is_closed,
                "open_time": open_time,
                "close_time": close_time,
            }
            existing = self.db.table("business_hours_exceptions").select("id").eq(
                "tenant_id", tenant_id
            ).eq("exception_date", exception_date.isoformat()).execute()

            if existing.data:
                self.db.table("business_hours_exceptions").update(row).eq(
                    "id", existing.data[0]["id"]
                ).execute()
            else:
                self.db.table("business_hours_exceptions").insert(row).execute()
            return True
        except Exception as e:
            logger.error(f"Error setting business hours exception for tenant {tenant_id}: {e}")
            return False

    async def set_bot_paused(self, tenant_id: str, paused: bool) -> bool:
        return await self._upsert_bot_config(tenant_id, {"bot_paused": paused})

    async def set_auto_reply_enabled(self, tenant_id: str, enabled: bool) -> bool:
        return await self._upsert_bot_config(tenant_id, {"auto_reply_enabled": enabled})

    async def set_offline_message(self, tenant_id: str, message: str) -> bool:
        return await self._upsert_bot_config(tenant_id, {"out_of_hours_message": message})
