"""
Advanced Analytics and Reporting (spec requirement 13 + requirement 21).

Every metric here is derived from tables that are ALREADY populated by the
existing bot pipeline - whatsapp_messages (logged for every inbound/outbound
message in meta_bot_service._log_message), orders, and post_sale_requests
(satisfaction_rating). The conversation_analytics table (sentiment/topic) is
deliberately NOT used here - nothing in the codebase writes to it today, and
building that ingestion (per-message sentiment analysis) is out of scope for
this pass.
"""
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import Counter
import logging

from db.supabase import get_supabase_client

logger = logging.getLogger(__name__)


class AdvancedAnalyticsService:
    """Conversion rate, response time, peak-activity, satisfaction analytics,
    and WhatsApp-formatted report generation for the seller."""

    def __init__(self, db=None):
        self.db = db or get_supabase_client()

    def _window_bounds(self, period_days: int, end_date: Optional[datetime] = None) -> Tuple[str, str]:
        end = end_date or datetime.now()
        start = end - timedelta(days=period_days)
        return start.isoformat(), end.isoformat()

    @staticmethod
    def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _top_key(counter: Counter) -> Optional[Any]:
        if not counter:
            return None
        return counter.most_common(1)[0][0]

    async def get_conversion_rate(
        self, tenant_id: str, period_days: int = 7, end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Orders / unique customers who messaged in the window - the
        standard "conversation to sale" conversion metric, not raw
        message-count based (a chatty customer shouldn't skew the rate)."""
        start_iso, end_iso = self._window_bounds(period_days, end_date)

        try:
            messages_result = self.db.table("whatsapp_messages").select(
                "sender_phone"
            ).eq("tenant_id", tenant_id).eq("direction", "inbound").gte(
                "created_at", start_iso
            ).lt("created_at", end_iso).execute()
            messages = messages_result.data or []
            unique_conversations = len({
                m["sender_phone"] for m in messages if m.get("sender_phone")
            })
        except Exception as e:
            logger.error(f"Error fetching messages for conversion rate, tenant {tenant_id}: {e}")
            unique_conversations = 0

        try:
            orders_result = self.db.table("orders").select("id").eq(
                "tenant_id", tenant_id
            ).gte("created_at", start_iso).lt("created_at", end_iso).execute()
            orders_count = len(orders_result.data or [])
        except Exception as e:
            logger.error(f"Error fetching orders for conversion rate, tenant {tenant_id}: {e}")
            orders_count = 0

        conversion_rate = (orders_count / unique_conversations) if unique_conversations else 0.0

        return {
            "period_days": period_days,
            "unique_conversations": unique_conversations,
            "orders_count": orders_count,
            "conversion_rate": conversion_rate,
        }

    async def get_response_time_metrics(self, tenant_id: str, period_days: int = 7) -> Dict[str, Any]:
        """Pairs each inbound message with the next outbound message to/from
        the same phone number to measure the bot's actual reply latency."""
        start_iso, end_iso = self._window_bounds(period_days)

        try:
            result = self.db.table("whatsapp_messages").select(
                "direction, sender_phone, receiver_phone, created_at"
            ).eq("tenant_id", tenant_id).gte("created_at", start_iso).lt(
                "created_at", end_iso
            ).order("created_at", desc=False).execute()
            messages = result.data or []
        except Exception as e:
            logger.error(f"Error fetching messages for response-time metrics, tenant {tenant_id}: {e}")
            messages = []

        deltas = self._compute_response_deltas(messages)
        if not deltas:
            return {"avg_response_seconds": None, "max_response_seconds": None, "sample_size": 0}

        return {
            "avg_response_seconds": sum(deltas) / len(deltas),
            "max_response_seconds": max(deltas),
            "sample_size": len(deltas),
        }

    def _compute_response_deltas(self, messages: List[Dict[str, Any]]) -> List[float]:
        pending_inbound: Dict[str, datetime] = {}
        deltas: List[float] = []

        for msg in messages:
            timestamp = self._parse_timestamp(msg.get("created_at"))
            if timestamp is None:
                continue

            if msg.get("direction") == "inbound":
                phone = msg.get("sender_phone")
                if phone:
                    pending_inbound[phone] = timestamp
            elif msg.get("direction") == "outbound":
                phone = msg.get("receiver_phone")
                if phone and phone in pending_inbound:
                    delta = (timestamp - pending_inbound.pop(phone)).total_seconds()
                    if delta >= 0:
                        deltas.append(delta)

        return deltas

    async def get_peak_activity(self, tenant_id: str, period_days: int = 30) -> Dict[str, Any]:
        """Peak hour/day of raw message activity vs. peak hour/day of actual
        orders - these can differ (e.g. busiest chat hour isn't always the
        busiest sales hour)."""
        start_iso, end_iso = self._window_bounds(period_days)

        try:
            messages_result = self.db.table("whatsapp_messages").select(
                "created_at"
            ).eq("tenant_id", tenant_id).eq("direction", "inbound").gte(
                "created_at", start_iso
            ).lt("created_at", end_iso).execute()
            messages = messages_result.data or []
        except Exception as e:
            logger.error(f"Error fetching messages for peak activity, tenant {tenant_id}: {e}")
            messages = []

        try:
            orders_result = self.db.table("orders").select("created_at").eq(
                "tenant_id", tenant_id
            ).gte("created_at", start_iso).lt("created_at", end_iso).execute()
            orders = orders_result.data or []
        except Exception as e:
            logger.error(f"Error fetching orders for peak activity, tenant {tenant_id}: {e}")
            orders = []

        activity_hours, activity_days = self._bucket_by_hour_and_weekday(messages)
        conversion_hours, conversion_days = self._bucket_by_hour_and_weekday(orders)

        return {
            "period_days": period_days,
            "peak_activity_hour": self._top_key(activity_hours),
            "peak_activity_day": self._top_key(activity_days),
            "peak_conversion_hour": self._top_key(conversion_hours),
            "peak_conversion_day": self._top_key(conversion_days),
        }

    def _bucket_by_hour_and_weekday(self, rows: List[Dict[str, Any]]) -> Tuple[Counter, Counter]:
        hours: Counter = Counter()
        days: Counter = Counter()
        for row in rows:
            timestamp = self._parse_timestamp(row.get("created_at"))
            if timestamp is None:
                continue
            hours[timestamp.hour] += 1
            days[timestamp.strftime("%A")] += 1
        return hours, days

    async def get_satisfaction_summary(self, tenant_id: str, period_days: int = 30) -> Dict[str, Any]:
        """Real satisfaction signal from post-sale request ratings (1-5),
        rather than inventing message-level sentiment analysis."""
        start_iso, end_iso = self._window_bounds(period_days)

        try:
            result = self.db.table("post_sale_requests").select(
                "satisfaction_rating, status"
            ).eq("tenant_id", tenant_id).gte("created_at", start_iso).lt(
                "created_at", end_iso
            ).execute()
            requests = result.data or []
        except Exception as e:
            logger.error(f"Error fetching satisfaction summary for tenant {tenant_id}: {e}")
            requests = []

        ratings = [r["satisfaction_rating"] for r in requests if r.get("satisfaction_rating") is not None]

        return {
            "period_days": period_days,
            "avg_rating": (sum(ratings) / len(ratings)) if ratings else None,
            "ratings_count": len(ratings),
            "resolved_count": len([r for r in requests if r.get("status") == "resolved"]),
            "open_count": len([r for r in requests if r.get("status") == "open"]),
        }

    async def generate_insights(self, tenant_id: str) -> List[str]:
        """Simple rule-based insights - no LLM call, just conditionals over
        the metrics above, kept cheap and predictable."""
        insights: List[str] = []

        conversion = await self.get_conversion_rate(tenant_id)
        if conversion["unique_conversations"] > 0:
            insights.append(
                f"Tu tasa de conversión de los últimos {conversion['period_days']} días es "
                f"{conversion['conversion_rate'] * 100:.1f}% ({conversion['orders_count']} pedidos de "
                f"{conversion['unique_conversations']} conversaciones)."
            )

        response_times = await self.get_response_time_metrics(tenant_id)
        if response_times["sample_size"] > 0:
            avg_seconds = response_times["avg_response_seconds"]
            if avg_seconds > 300:
                insights.append(
                    f"Tu tiempo de respuesta promedio es de {avg_seconds / 60:.1f} minutos - "
                    "esto puede estar afectando tus ventas, considera revisar la configuración del bot."
                )
            else:
                insights.append(f"Tu tiempo de respuesta promedio es de {avg_seconds:.0f} segundos.")

        peak_activity = await self.get_peak_activity(tenant_id)
        if peak_activity["peak_activity_hour"] is not None:
            insights.append(
                f"Tu hora de mayor actividad es las {peak_activity['peak_activity_hour']}:00 - "
                "asegúrate de tener stock y personal disponible en ese horario."
            )

        satisfaction = await self.get_satisfaction_summary(tenant_id)
        if satisfaction["ratings_count"] > 0:
            insights.append(
                f"Tu calificación de satisfacción promedio es {satisfaction['avg_rating']:.1f}/5 "
                f"({satisfaction['ratings_count']} calificaciones)."
            )

        if not insights:
            insights.append("Aún no hay suficientes datos para generar insights. Vuelve a consultar en unos días.")

        return insights

    async def generate_daily_report(self, tenant_id: str) -> str:
        """Combines the existing daily order summary with conversion +
        insights, reusing ConversationalDashboard instead of duplicating its
        order-summary logic. Imported locally to avoid a module-load-time
        circular import (ConversationalDashboard also references this
        service for its new WhatsApp commands)."""
        from services.conversational_dashboard import ConversationalDashboard

        dashboard = ConversationalDashboard(db=self.db)
        summary_data = await dashboard.get_daily_summary(tenant_id)
        summary_text = dashboard._format_daily_summary(summary_data)

        conversion = await self.get_conversion_rate(tenant_id, period_days=1)
        insights = await self.generate_insights(tenant_id)

        lines = [
            summary_text,
            "",
            f"📊 *Conversión de hoy:* {conversion['orders_count']} pedidos de "
            f"{conversion['unique_conversations']} conversaciones "
            f"({conversion['conversion_rate'] * 100:.1f}%)",
        ]
        if insights:
            lines.append("")
            lines.append("💡 *Insights:*")
            lines.extend(f"• {insight}" for insight in insights)

        return "\n".join(lines)

    async def generate_weekly_report(self, tenant_id: str) -> str:
        """Compares this week against the prior 7-day window - each computed
        as an independent bounded range, not by subtracting a 14-day total
        from a 7-day total (which would double-count returning customers)."""
        now = datetime.now()
        current_week = await self.get_conversion_rate(tenant_id, period_days=7, end_date=now)
        previous_week = await self.get_conversion_rate(
            tenant_id, period_days=7, end_date=now - timedelta(days=7)
        )
        insights = await self.generate_insights(tenant_id)

        lines = [
            "📅 *Reporte semanal*",
            "",
            f"🛒 Pedidos esta semana: {current_week['orders_count']} "
            f"({self._trend(current_week['orders_count'], previous_week['orders_count'])} vs. semana anterior)",
            f"💬 Conversaciones: {current_week['unique_conversations']} "
            f"({self._trend(current_week['unique_conversations'], previous_week['unique_conversations'])} vs. semana anterior)",
            f"📊 Tasa de conversión: {current_week['conversion_rate'] * 100:.1f}% "
            f"(semana anterior: {previous_week['conversion_rate'] * 100:.1f}%)",
        ]
        if insights:
            lines.append("")
            lines.append("💡 *Insights:*")
            lines.extend(f"• {insight}" for insight in insights)

        return "\n".join(lines)

    @staticmethod
    def _trend(current: float, previous: float) -> str:
        if previous == 0:
            return "🆕" if current > 0 else "➡️ 0%"
        change_pct = (current - previous) / previous * 100
        arrow = "📈" if change_pct > 0 else "📉" if change_pct < 0 else "➡️"
        return f"{arrow} {change_pct:+.0f}%"
