"""
Conversational Dashboard for Vendly Pro
Implements WhatsApp-based interface for business owners with smart alerts system
"""
from typing import Dict, Any, Optional, List
import logging
from datetime import datetime, timedelta
import json
from dataclasses import dataclass
from enum import Enum

from db.supabase import get_supabase_client
from services.advanced_analytics_service import AdvancedAnalyticsService

logger = logging.getLogger(__name__)


class AlertType(str, Enum):
    """Types of smart alerts"""
    LOW_STOCK = "low_stock"
    VIP_CUSTOMER = "vip_customer"
    SALES_ANOMALY = "sales_anomaly"
    NEGATIVE_FEEDBACK = "negative_feedback"


@dataclass
class AlertConfig:
    """Configuration for smart alerts"""
    alert_type: AlertType
    enabled: bool = True
    threshold: Optional[float] = None
    notification_phone: Optional[str] = None
    last_triggered: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            "alert_type": self.alert_type.value,
            "enabled": self.enabled,
            "threshold": self.threshold,
            "notification_phone": self.notification_phone,
            "last_triggered": self.last_triggered.isoformat() if self.last_triggered else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AlertConfig':
        """Create from dictionary"""
        # Handle missing or invalid alert_type
        alert_type_value = data.get("alert_type")
        if not alert_type_value:
            raise ValueError("Missing 'alert_type' in alert config data")
        
        try:
            alert_type = AlertType(alert_type_value)
        except ValueError:
            # Try to handle string values that might not match enum exactly
            alert_type_str = str(alert_type_value).lower()
            for enum_member in AlertType:
                if enum_member.value == alert_type_str:
                    alert_type = enum_member
                    break
            else:
                # Default to LOW_STOCK if cannot determine
                alert_type = AlertType.LOW_STOCK
        
        # Handle last_triggered
        last_triggered = None
        if data.get("last_triggered"):
            try:
                last_triggered = datetime.fromisoformat(data["last_triggered"])
            except (ValueError, TypeError):
                # If date format is invalid, ignore it
                last_triggered = None
        
        return cls(
            alert_type=alert_type,
            enabled=data.get("enabled", True),
            threshold=data.get("threshold"),
            notification_phone=data.get("notification_phone"),
            last_triggered=last_triggered
        )


class ConversationalDashboard:
    """WhatsApp-based dashboard for business owners with smart alerts"""
    
    def __init__(self, db=None):
        self.db = db or get_supabase_client()
        self.advanced_analytics = AdvancedAnalyticsService(db=self.db)

    async def process_seller_command(
        self,
        tenant_id: str,
        seller_phone: str,
        command: str
    ) -> str:
        """Process seller commands like 'resumen', 'analytics', 'stock', 'alertas'"""
        command_lower = command.lower().strip()

        if "resumen" in command_lower:
            summary_data = await self.get_daily_summary(tenant_id)
            return self._format_daily_summary(summary_data)
        elif "analytics" in command_lower or "estadísticas" in command_lower:
            analytics_data = await self.get_conversation_analytics(tenant_id)
            return self._format_conversation_analytics(analytics_data)
        elif "tiempo respuesta" in command_lower or "tiempo de respuesta" in command_lower:
            return await self._format_response_time(tenant_id)
        elif "conversión" in command_lower or "conversion" in command_lower:
            return await self._format_conversion_rate(tenant_id)
        elif "horas pico" in command_lower or "horario pico" in command_lower:
            return await self._format_peak_activity(tenant_id)
        elif "reporte" in command_lower:
            return await self.advanced_analytics.generate_daily_report(tenant_id)
        elif "stock" in command_lower or "inventario" in command_lower:
            if "actualizar" in command_lower:
                return await self._process_stock_update(tenant_id, command)
            elif "alertas" in command_lower or "configurar" in command_lower:
                return await self._configure_stock_alerts(tenant_id, command)
            else:
                return await self._send_stock_status(tenant_id)
        elif "alertas" in command_lower:
            if "configurar" in command_lower or "config" in command_lower:
                return await self._configure_alerts_menu(tenant_id)
            else:
                return await self._show_active_alerts(tenant_id)
        elif "preguntas frecuentes" in command_lower or "faq" in command_lower:
            return await self._get_frequent_questions(tenant_id)
        elif "config" in command_lower or "configuración" in command_lower:
            return await self._get_configuration_menu(tenant_id)
        else:
            return await self._get_dashboard_menu()
    
    async def get_daily_summary(self, tenant_id: str) -> Dict[str, Any]:
        """Generate daily summary with key metrics"""
        try:
            today = datetime.now().date()
            today_str = today.isoformat()
            
            # Get today's orders
            orders_result = self.db.table("orders").select(
                "id, total, status, created_at"
            ).eq("tenant_id", tenant_id).gte("created_at", today_str).execute()
            
            orders = orders_result.data if orders_result.data else []
            
            # Calculate metrics
            total_orders = len(orders)
            completed_orders = len([o for o in orders if o["status"] in ["completed", "delivered"]])
            pending_orders = len([o for o in orders if o["status"] in ["pending", "payment_pending"]])
            total_revenue = sum(float(o.get("total", 0) or 0) for o in orders if o["status"] in ["completed", "delivered"])
            
            # Get new customers (first order today)
            new_customers = set()
            for order in orders:
                # Get customer phone from order
                order_details = self.db.table("order_details").select(
                    "customer_phone"
                ).eq("order_id", order["id"]).execute()
                
                if order_details.data:
                    # Check if this is their first order
                    customer_phone = order_details.data[0]["customer_phone"]
                    previous_orders = self.db.table("orders").select("id").eq(
                        "tenant_id", tenant_id
                    ).lt("created_at", today_str).execute()
                    
                    # Check if customer has previous orders
                    has_previous = False
                    for prev_order in previous_orders.data:
                        prev_details = self.db.table("order_details").select(
                            "customer_phone"
                        ).eq("order_id", prev_order["id"]).execute()
                        
                        if prev_details.data and prev_details.data[0]["customer_phone"] == customer_phone:
                            has_previous = True
                            break
                    
                    if not has_previous:
                        new_customers.add(customer_phone)
            
            # Calculate average order value
            avg_order_value = total_revenue / completed_orders if completed_orders > 0 else 0
            
            return {
                "date": today_str,
                "total_orders": total_orders,
                "completed_orders": completed_orders,
                "pending_orders": pending_orders,
                "total_revenue": total_revenue,
                "new_customers": len(new_customers),
                "avg_order_value": avg_order_value,
                "orders": orders[:10]  # First 10 orders for details
            }
            
        except Exception as e:
            logger.error(f"Error getting daily summary: {e}")
            raise
    
    async def get_conversation_analytics(self, tenant_id: str) -> Dict[str, Any]:
        """Analyze customer conversations for trends"""
        try:
            # Get last 7 days of conversation analytics
            seven_days_ago = (datetime.now() - timedelta(days=7)).date().isoformat()
            
            analytics_result = self.db.table("conversation_analytics").select(
                "message_type, topic, sentiment_score, conversation_date"
            ).eq("tenant_id", tenant_id).gte("conversation_date", seven_days_ago).execute()
            
            analytics = analytics_result.data if analytics_result.data else []
            
            # Calculate trends
            message_types = {}
            topics = {}
            sentiment_scores = []
            
            for item in analytics:
                # Count message types
                msg_type = item.get("message_type", "unknown")
                message_types[msg_type] = message_types.get(msg_type, 0) + 1
                
                # Count topics
                topic = item.get("topic", "unknown")
                if topic:
                    topics[topic] = topics.get(topic, 0) + 1
                
                # Collect sentiment scores
                sentiment = item.get("sentiment_score")
                if sentiment is not None:
                    sentiment_scores.append(float(sentiment))
            
            # Calculate average sentiment
            avg_sentiment = sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0
            
            # Get most common questions
            common_questions = sorted(topics.items(), key=lambda x: x[1], reverse=True)[:5]
            
            return {
                "period": "last_7_days",
                "total_conversations": len(analytics),
                "message_types": message_types,
                "common_topics": dict(common_questions),
                "avg_sentiment": avg_sentiment,
                "positive_conversations": len([s for s in sentiment_scores if s > 0.3]),
                "negative_conversations": len([s for s in sentiment_scores if s < -0.3]),
                "neutral_conversations": len([s for s in sentiment_scores if -0.3 <= s <= 0.3])
            }
            
        except Exception as e:
            logger.error(f"Error getting conversation analytics: {e}")
            raise
    
    def _format_daily_summary(self, summary_data: Dict[str, Any]) -> str:
        """Format daily summary data as a readable string"""
        try:
            date = summary_data.get("date", "")
            total_orders = summary_data.get("total_orders", 0)
            completed_orders = summary_data.get("completed_orders", 0)
            pending_orders = summary_data.get("pending_orders", 0)
            total_revenue = summary_data.get("total_revenue", 0)
            new_customers = summary_data.get("new_customers", 0)
            avg_order_value = summary_data.get("avg_order_value", 0)
            
            message = f"📊 *Resumen del Día - {date}*\n\n"
            message += f"📦 *Pedidos totales:* {total_orders}\n"
            message += f"✅ *Completados:* {completed_orders}\n"
            message += f"⏳ *Pendientes:* {pending_orders}\n"
            message += f"💰 *Ingresos:* ${total_revenue:.2f}\n"
            message += f"👥 *Nuevos clientes:* {new_customers}\n"
            message += f"📈 *Valor promedio por pedido:* ${avg_order_value:.2f}\n\n"
            
            if "orders" in summary_data and summary_data["orders"]:
                message += "*Últimos pedidos:*\n"
                for i, order in enumerate(summary_data["orders"][:5], 1):
                    order_time = datetime.fromisoformat(order["created_at"]).strftime("%H:%M")
                    status_emoji = "✅" if order["status"] in ["completed", "delivered"] else "⏳"
                    message += f"{i}. {status_emoji} ${order['total']} a las {order_time}\n"
            
            return message
            
        except Exception as e:
            logger.error(f"Error formatting daily summary: {e}")
            return "Error al generar el resumen del día."
    
    def _format_conversation_analytics(self, analytics_data: Dict[str, Any]) -> str:
        """Format conversation analytics data as a readable string"""
        try:
            period = analytics_data.get("period", "Últimos 7 días")
            total_conversations = analytics_data.get("total_conversations", 0)
            message_types = analytics_data.get("message_types", {})
            common_topics = analytics_data.get("common_topics", {})
            avg_sentiment = analytics_data.get("avg_sentiment", 0)
            positive = analytics_data.get("positive_conversations", 0)
            negative = analytics_data.get("negative_conversations", 0)
            neutral = analytics_data.get("neutral_conversations", 0)
            
            message = f"📈 *Análisis de Conversaciones - {period}*\n\n"
            message += f"💬 *Total conversaciones:* {total_conversations}\n\n"
            
            if message_types:
                message += "*Tipos de mensajes:*\n"
                for msg_type, count in sorted(message_types.items(), key=lambda x: x[1], reverse=True)[:5]:
                    message += f"• {msg_type}: {count}\n"
                message += "\n"
            
            if common_topics:
                message += "*Temas más comunes:*\n"
                for topic, count in sorted(common_topics.items(), key=lambda x: x[1], reverse=True)[:5]:
                    message += f"• {topic}: {count} veces\n"
                message += "\n"
            
            sentiment_emoji = "😊" if avg_sentiment > 0.3 else "😐" if avg_sentiment > -0.3 else "😞"
            message += f"😊 *Sentimiento promedio:* {sentiment_emoji} {avg_sentiment:.2f}\n"
            message += f"✅ *Positivas:* {positive}\n"
            message += f"😐 *Neutrales:* {neutral}\n"
            message += f"❌ *Negativas:* {negative}\n\n"
            
            message += "Usa 'preguntas frecuentes' para ver las preguntas más comunes."
            
            return message
            
        except Exception as e:
            logger.error(f"Error formatting conversation analytics: {e}")
            return "Error al generar análisis de conversaciones."

    async def _format_response_time(self, tenant_id: str) -> str:
        """WhatsApp reply for the 'tiempo respuesta' seller command"""
        try:
            metrics = await self.advanced_analytics.get_response_time_metrics(tenant_id)
            if metrics["sample_size"] == 0:
                return "Todavía no hay suficientes conversaciones para calcular el tiempo de respuesta."

            avg_seconds = metrics["avg_response_seconds"]
            max_seconds = metrics["max_response_seconds"]
            return (
                "⏱️ *Tiempo de respuesta del bot*\n\n"
                f"Promedio: {avg_seconds:.0f} segundos\n"
                f"Máximo (pico): {max_seconds:.0f} segundos\n"
                f"Basado en {metrics['sample_size']} respuestas de los últimos 7 días."
            )
        except Exception as e:
            logger.error(f"Error formatting response time for tenant {tenant_id}: {e}")
            return "Error al calcular el tiempo de respuesta."

    async def _format_conversion_rate(self, tenant_id: str) -> str:
        """WhatsApp reply for the 'conversión' seller command"""
        try:
            conversion = await self.advanced_analytics.get_conversion_rate(tenant_id)
            return (
                "📊 *Tasa de conversión (últimos 7 días)*\n\n"
                f"Conversaciones: {conversion['unique_conversations']}\n"
                f"Pedidos: {conversion['orders_count']}\n"
                f"Tasa de conversión: {conversion['conversion_rate'] * 100:.1f}%"
            )
        except Exception as e:
            logger.error(f"Error formatting conversion rate for tenant {tenant_id}: {e}")
            return "Error al calcular la tasa de conversión."

    async def _format_peak_activity(self, tenant_id: str) -> str:
        """WhatsApp reply for the 'horas pico' seller command"""
        try:
            peak = await self.advanced_analytics.get_peak_activity(tenant_id)
            if peak["peak_activity_hour"] is None:
                return "Todavía no hay suficiente actividad para identificar horas pico."

            message = (
                "🕐 *Horas y días de mayor actividad (últimos 30 días)*\n\n"
                f"Hora con más mensajes: {peak['peak_activity_hour']}:00\n"
            )
            if peak.get("peak_activity_day"):
                message += f"Día con más mensajes: {peak['peak_activity_day']}\n"
            if peak.get("peak_conversion_hour") is not None:
                message += f"Hora con más pedidos: {peak['peak_conversion_hour']}:00\n"
            if peak.get("peak_conversion_day"):
                message += f"Día con más pedidos: {peak['peak_conversion_day']}\n"

            return message
        except Exception as e:
            logger.error(f"Error formatting peak activity for tenant {tenant_id}: {e}")
            return "Error al calcular las horas pico."

    async def send_smart_alert(
        self,
        tenant_id: str,
        alert_type: AlertType,
        data: Dict[str, Any],
        config: Optional["AlertConfig"] = None
    ) -> str:
        """Send proactive alert to seller.

        `config` can be passed in by callers (like the `_check_*` methods)
        that already fetched it, to avoid a redundant DB round-trip.
        """
        try:
            if isinstance(alert_type, str):
                alert_type = AlertType(alert_type)

            # Get alert configuration (unless already provided by the caller)
            if config is None:
                config = await self._get_alert_config(tenant_id, alert_type)

            if not config or not config.enabled:
                logger.info(f"Alert {alert_type} disabled for tenant {tenant_id}")
                return None
            
            # Check if alert was recently triggered (cooldown)
            if config.last_triggered:
                cooldown_hours = self._get_alert_cooldown(alert_type)
                if (datetime.now() - config.last_triggered).total_seconds() < cooldown_hours * 3600:
                    logger.info(f"Alert {alert_type} in cooldown for tenant {tenant_id}")
                    return None
            
            # Generate alert message based on type
            alert_message = self._generate_alert_message(alert_type, data)
            
            if not alert_message:
                logger.warning(f"Could not generate alert message for {alert_type}")
                return None
            
            # Update last triggered time
            await self._update_alert_last_triggered(tenant_id, alert_type)
            
            return alert_message
            
        except Exception as e:
            logger.error(f"Error sending smart alert: {e}")
            return None
    
    async def check_and_send_alerts(self, tenant_id: str) -> List[str]:
        """Check all alert conditions and send notifications"""
        alerts_sent = []
        
        try:
            # Check low stock alerts
            low_stock_alert = await self._check_low_stock(tenant_id)
            if low_stock_alert:
                alerts_sent.append(low_stock_alert)
            
            # Check VIP customer alerts
            vip_alert = await self._check_vip_customers(tenant_id)
            if vip_alert:
                alerts_sent.append(vip_alert)
            
            # Check sales anomaly alerts
            anomaly_alert = await self._check_sales_anomalies(tenant_id)
            if anomaly_alert:
                alerts_sent.append(anomaly_alert)
            
            # Check negative feedback alerts
            feedback_alert = await self._check_negative_feedback(tenant_id)
            if feedback_alert:
                alerts_sent.append(feedback_alert)
            
            return alerts_sent
            
        except Exception as e:
            logger.error(f"Error checking alerts: {e}")
            return []
    
    async def _check_low_stock(self, tenant_id: str) -> Optional[str]:
        """Check for low stock products"""
        try:
            # Get alert configuration
            config = await self._get_alert_config(tenant_id, AlertType.LOW_STOCK)
            
            if not config or not config.enabled:
                return None
            
            threshold = config.threshold or 5  # Default threshold
            
            # Get products with stock below threshold
            items_result = self.db.table("items").select(
                "name, stock_quantity"
            ).eq("tenant_id", tenant_id).eq("is_active", True).eq("track_stock", True).lt(
                "stock_quantity", threshold
            ).execute()
            
            low_stock_items = [
                item for item in items_result.data if item.get("stock_quantity", 0) < threshold
            ] if items_result.data else []

            if not low_stock_items:
                return None
            
            # Generate alert message
            alert_data = {
                "threshold": threshold,
                "low_stock_items": low_stock_items,
                "total_low_stock": len(low_stock_items)
            }
            
            return await self.send_smart_alert(tenant_id, AlertType.LOW_STOCK, alert_data, config=config)
            
        except Exception as e:
            logger.error(f"Error checking low stock: {e}")
            return None
    
    async def _check_vip_customers(self, tenant_id: str) -> Optional[str]:
        """Check for VIP customer orders"""
        try:
            # Get alert configuration
            config = await self._get_alert_config(tenant_id, AlertType.VIP_CUSTOMER)
            
            if not config or not config.enabled:
                return None
            
            # Get VIP customers (based on total spent or tier)
            vip_customers_result = self.db.table("customer_profiles").select(
                "phone_number, total_spent, last_purchase_date"
            ).eq("tenant_id", tenant_id).gt("total_spent", 100).execute()  # Example: VIP if spent > $100
            
            vip_customers = vip_customers_result.data if vip_customers_result.data else []
            
            if not vip_customers:
                return None
            
            # Check for recent orders from VIP customers (last 24 hours)
            twenty_four_hours_ago = (datetime.now() - timedelta(hours=24)).isoformat()
            
            recent_vip_orders = []
            for vip in vip_customers:
                orders_result = self.db.table("orders").select(
                    "id, total, created_at"
                ).eq("tenant_id", tenant_id).gte("created_at", twenty_four_hours_ago).execute()
                
                # Check if any order belongs to this VIP customer
                for order in orders_result.data:
                    order_details = self.db.table("order_details").select(
                        "customer_phone"
                    ).eq("order_id", order["id"]).execute()
                    
                    if order_details.data and order_details.data[0]["customer_phone"] == vip["phone_number"]:
                        recent_vip_orders.append({
                            "customer": vip,
                            "order": order
                        })
            
            if not recent_vip_orders:
                return None
            
            # Generate alert message
            alert_data = {
                "vip_orders": recent_vip_orders,
                "total_vip_orders": len(recent_vip_orders)
            }
            
            return await self.send_smart_alert(tenant_id, AlertType.VIP_CUSTOMER, alert_data, config=config)
            
        except Exception as e:
            logger.error(f"Error checking VIP customers: {e}")
            return None
    
    async def _check_sales_anomalies(self, tenant_id: str) -> Optional[str]:
        """Check for anomalies in sales patterns"""
        try:
            # Get alert configuration
            config = await self._get_alert_config(tenant_id, AlertType.SALES_ANOMALY)
            
            if not config or not config.enabled:
                return None
            
            # Get sales data for last 7 days
            seven_days_ago = (datetime.now() - timedelta(days=7)).date().isoformat()
            
            orders_result = self.db.table("orders").select(
                "created_at, total, status"
            ).eq("tenant_id", tenant_id).gte("created_at", seven_days_ago).execute()
            
            orders = orders_result.data if orders_result.data else []
            
            if len(orders) < 3:  # Need at least 3 days of data
                return None
            
            # Group orders by day
            daily_sales = {}
            for order in orders:
                if order["status"] in ["completed", "delivered"]:
                    order_date = datetime.fromisoformat(order["created_at"]).date()
                    day_key = order_date.isoformat()
                    daily_sales[day_key] = daily_sales.get(day_key, 0) + float(order.get("total", 0) or 0)
            
            # Calculate average and standard deviation
            sales_values = list(daily_sales.values())
            if len(sales_values) < 3:
                return None
            
            avg_sales = sum(sales_values) / len(sales_values)
            
            # Check for anomalies (sales drop > 50% from average)
            threshold = config.threshold or 0.5  # Default 50% drop
            anomalies = []
            
            for date_str, sales in daily_sales.items():
                if sales < avg_sales * (1 - threshold):
                    anomalies.append({
                        "date": date_str,
                        "sales": sales,
                        "expected": avg_sales,
                        "drop_percentage": (avg_sales - sales) / avg_sales * 100
                    })
            
            if not anomalies:
                return None
            
            # Generate alert message
            alert_data = {
                "anomalies": anomalies,
                "average_sales": avg_sales,
                "threshold_percentage": threshold * 100
            }
            
            return await self.send_smart_alert(tenant_id, AlertType.SALES_ANOMALY, alert_data, config=config)
            
        except Exception as e:
            logger.error(f"Error checking sales anomalies: {e}")
            return None
    
    async def _check_negative_feedback(self, tenant_id: str) -> Optional[str]:
        """Check for negative feedback from customers"""
        try:
            # Get alert configuration
            config = await self._get_alert_config(tenant_id, AlertType.NEGATIVE_FEEDBACK)
            
            if not config or not config.enabled:
                return None
            
            # Get negative feedback from conversation analytics (last 24 hours)
            twenty_four_hours_ago = (datetime.now() - timedelta(hours=24)).isoformat()
            
            feedback_result = self.db.table("conversation_analytics").select(
                "customer_phone, sentiment_score, conversation_date"
            ).eq("tenant_id", tenant_id).gte("conversation_date", twenty_four_hours_ago).lt(
                "sentiment_score", -0.5  # Strong negative sentiment
            ).execute()
            
            negative_feedback = feedback_result.data if feedback_result.data else []
            
            if not negative_feedback:
                return None
            
            # Generate alert message
            alert_data = {
                "negative_feedback_count": len(negative_feedback),
                "feedback_items": negative_feedback[:5]  # First 5 items
            }
            
            return await self.send_smart_alert(tenant_id, AlertType.NEGATIVE_FEEDBACK, alert_data, config=config)
            
        except Exception as e:
            logger.error(f"Error checking negative feedback: {e}")
            return None
    
    async def _get_alert_config(self, tenant_id: str, alert_type: AlertType) -> Optional[AlertConfig]:
        """Get alert configuration from database"""
        try:
            if isinstance(alert_type, str) and not isinstance(alert_type, AlertType):
                alert_type = AlertType(alert_type)

            result = self.db.table("alert_configs").select("*").eq(
                "tenant_id", tenant_id
            ).eq("alert_type", alert_type.value).execute()
            
            if result.data and result.data[0]:
                try:
                    return AlertConfig.from_dict(result.data[0])
                except (ValueError, KeyError) as e:
                    logger.warning(f"Invalid alert config data for tenant {tenant_id}, alert_type {alert_type}: {e}")
                    # Create default configuration
                    default_config = AlertConfig(alert_type=alert_type)
                    await self._save_alert_config(tenant_id, default_config)
                    return default_config
            
            # Create default configuration if not exists
            default_config = AlertConfig(alert_type=alert_type)
            await self._save_alert_config(tenant_id, default_config)
            return default_config
            
        except Exception as e:
            logger.error(f"Error getting alert config: {e}")
            return None
    
    async def _save_alert_config(self, tenant_id: str, config: AlertConfig) -> bool:
        """Save alert configuration to database"""
        try:
            if isinstance(config.alert_type, str) and not isinstance(config.alert_type, AlertType):
                config.alert_type = AlertType(config.alert_type)

            config_dict = config.to_dict()
            config_dict["tenant_id"] = tenant_id
            
            # Check if config exists
            existing = self.db.table("alert_configs").select("id").eq(
                "tenant_id", tenant_id
            ).eq("alert_type", config.alert_type.value).execute()
            
            if existing.data:
                # Update existing
                result = self.db.table("alert_configs").update(config_dict).eq(
                    "tenant_id", tenant_id
                ).eq("alert_type", config.alert_type.value).execute()
            else:
                # Insert new
                result = self.db.table("alert_configs").insert(config_dict).execute()
            
            return bool(result.data)
            
        except Exception as e:
            logger.error(f"Error saving alert config: {e}")
            return False
    
    async def _update_alert_last_triggered(self, tenant_id: str, alert_type: AlertType) -> None:
        """Update last triggered time for an alert"""
        try:
            self.db.table("alert_configs").update({
                "last_triggered": datetime.now().isoformat()
            }).eq("tenant_id", tenant_id).eq("alert_type", alert_type.value).execute()
        except Exception as e:
            logger.error(f"Error updating last triggered: {e}")
    
    def _generate_alert_message(self, alert_type: AlertType, data: Dict[str, Any]) -> str:
        """Generate alert message based on type and data"""
        if alert_type == AlertType.LOW_STOCK:
            items = data.get("low_stock_items", [])
            threshold = data.get("threshold", 5)
            
            message = f"⚠️ *ALERTA: Stock Bajo*\n\n"
            message += f"Hay {len(items)} productos con stock por debajo de {threshold} unidades:\n\n"
            
            for item in items[:5]:  # Show first 5 items
                message += f"• {item['name']}: {item['stock_quantity']} unidades\n"
            
            if len(items) > 5:
                message += f"\n...y {len(items) - 5} productos más.\n"
            
            message += "\nUsa 'actualizar stock' para reponer inventario."
            return message
            
        elif alert_type == AlertType.VIP_CUSTOMER:
            orders = data.get("vip_orders", [])
            
            message = f"⭐ *ALERTA: Cliente VIP*\n\n"
            message += f"Clientes VIP han realizado {len(orders)} pedidos:\n\n"
            
            for order_info in orders[:3]:  # Show first 3 orders
                customer = order_info["customer"]
                order = order_info["order"]
                order_date = datetime.fromisoformat(order["created_at"]).strftime("%H:%M")
                
                message += f"• {customer['phone_number']}: ${order['total']} a las {order_date}\n"
            
            if len(orders) > 3:
                message += f"\n...y {len(orders) - 3} pedidos más.\n"
            
            message += "\nConsidera ofrecer atención especial o agradecimiento."
            return message
            
        elif alert_type == AlertType.SALES_ANOMALY:
            anomalies = data.get("anomalies", [])
            avg_sales = data.get("average_sales", 0)
            threshold = data.get("threshold_percentage", 50)
            
            message = f"📉 *ALERTA: Anomalía en Ventas*\n\n"
            message += f"Se detectó una caída del {threshold}% en las ventas:\n\n"
            
            for anomaly in anomalies[:3]:  # Show first 3 anomalies
                message += f"• {anomaly['date']}: ${anomaly['sales']:.2f} (esperado: ${anomaly['expected']:.2f})\n"
                message += f"  Caída: {anomaly['drop_percentage']:.1f}%\n"
            
            message += f"\nVentas promedio: ${avg_sales:.2f}"
            message += "\n\nRevisa posibles causas: horarios, productos, competencia."
            return message
            
        elif alert_type == AlertType.NEGATIVE_FEEDBACK:
            feedback_count = data.get("negative_feedback_count", 0)
            feedback_items = data.get("feedback_items", [])
            
            message = f"😞 *ALERTA: Feedback Negativo*\n\n"
            message += f"Se recibió {feedback_count} feedback negativo:\n\n"
            
            for feedback in feedback_items[:3]:  # Show first 3 feedback items
                customer_phone = feedback.get("customer_phone", "Desconocido")
                sentiment = float(feedback.get("sentiment_score", 0))
                
                # Handle conversation_date if present
                if "conversation_date" in feedback and feedback["conversation_date"]:
                    try:
                        feedback_date = datetime.fromisoformat(feedback["conversation_date"]).strftime("%H:%M")
                        message += f"• Cliente {customer_phone} a las {feedback_date}\n"
                    except (ValueError, TypeError):
                        message += f"• Cliente {customer_phone}\n"
                else:
                    message += f"• Cliente {customer_phone}\n"
                
                message += f"  Sentimiento: {sentiment:.2f}\n"
            
            message += "\nConsidera contactar a los clientes para resolver problemas."
            return message
        
        return None
    
    def _get_alert_cooldown(self, alert_type: AlertType) -> int:
        """Get cooldown period in hours for each alert type"""
        cooldowns = {
            AlertType.LOW_STOCK: 4,        # 4 hours
            AlertType.VIP_CUSTOMER: 1,     # 1 hour
            AlertType.SALES_ANOMALY: 24,   # 24 hours
            AlertType.NEGATIVE_FEEDBACK: 1 # 1 hour
        }
        return cooldowns.get(alert_type, 1)
    
    async def _send_stock_status(self, tenant_id: str) -> str:
        """Send stock status to seller"""
        try:
            # Get products with stock tracking
            items_result = self.db.table("items").select(
                "name, stock_quantity"
            ).eq("tenant_id", tenant_id).eq("is_active", True).eq("track_stock", True).execute()
            
            if not items_result.data:
                return "No hay productos con control de stock."
            
            low_stock_items = [item for item in items_result.data if item["stock_quantity"] <= 5]
            normal_stock_items = [item for item in items_result.data if item["stock_quantity"] > 5]
            
            message = "📦 *Estado del Inventario:*\n\n"
            
            if low_stock_items:
                message += "⚠️ *Stock Bajo:*\n"
                for item in low_stock_items:
                    message += f"• {item['name']}: {item['stock_quantity']} unidades\n"
                message += "\n"
            
            if normal_stock_items:
                message += "✅ *Stock Normal:*\n"
                for item in normal_stock_items[:5]:  # Limit to 5 items
                    message += f"• {item['name']}: {item['stock_quantity']} unidades\n"
            
            return message
            
        except Exception as e:
            logger.error(f"Error getting stock status: {e}")
            return "Error al consultar estado del inventario."
    
    async def _process_stock_update(self, tenant_id: str, command: str) -> str:
        """Process stock update command"""
        try:
            # Parse message: "actualizar stock [producto] [cantidad]"
            parts = command.split()
            if len(parts) < 4:
                return "Formato incorrecto. Usa: actualizar stock [producto] [cantidad]"
            
            product_name = " ".join(parts[2:-1])
            quantity = int(parts[-1])
            
            # Find product
            items_result = self.db.table("items").select("id, name").eq(
                "tenant_id", tenant_id
            ).eq("name", product_name).eq("is_active", True).execute()
            
            if not items_result.data:
                return f"Producto '{product_name}' no encontrado."
            
            # Update stock
            item_id = items_result.data[0]["id"]
            result = self.db.table("items").update({
                "stock_quantity": quantity,
                "updated_at": datetime.now().isoformat()
            }).eq("id", item_id).execute()
            
            if result.data:
                return f"✅ Stock de '{product_name}' actualizado a {quantity} unidades."
            else:
                return f"Error actualizando stock de '{product_name}'."
                
        except ValueError:
            return "Cantidad inválida. Usa: actualizar stock [producto] [cantidad]"
        except Exception as e:
            logger.error(f"Error updating stock: {e}")
            return "Error al actualizar stock."
    
    async def _configure_stock_alerts(self, tenant_id: str, command: str) -> str:
        """Configure stock alert thresholds"""
        try:
            # Parse command: "configurar alertas stock [umbral]"
            parts = command.split()
            if len(parts) < 4:
                return "Formato: configurar alertas stock [umbral] (ej: configurar alertas stock 10)"
            
            threshold = int(parts[-1])
            
            # Update or create alert config
            config = AlertConfig(
                alert_type=AlertType.LOW_STOCK,
                enabled=True,
                threshold=threshold
            )
            
            success = await self._save_alert_config(tenant_id, config)
            
            if success:
                return f"✅ Alertas de stock configuradas con umbral de {threshold} unidades."
            else:
                return "Error configurando alertas de stock."
                
        except ValueError:
            return "Umbral inválido. Usa un número (ej: configurar alertas stock 10)"
        except Exception as e:
            logger.error(f"Error configuring stock alerts: {e}")
            return "Error configurando alertas de stock."
    
    async def _configure_alerts_menu(self, tenant_id: str) -> str:
        """Show alert configuration menu"""
        return """🔔 *Configuración de Alertas*

Configura alertas inteligentes para tu negocio:

1️⃣ *Stock bajo* - Recibe alertas cuando productos tengan poco stock
   Comando: "configurar alertas stock [umbral]"
   Ejemplo: "configurar alertas stock 10"

2️⃣ *Clientes VIP* - Alertas cuando clientes importantes realicen pedidos
   Comando: "activar alertas vip" o "desactivar alertas vip"

3️⃣ *Anomalías en ventas* - Detecta caídas súbitas en ventas
   Comando: "configurar alertas anomalias [porcentaje]"
   Ejemplo: "configurar alertas anomalias 50"

4️⃣ *Feedback negativo* - Alertas cuando clientes dejen feedback negativo
   Comando: "activar alertas feedback" o "desactivar alertas feedback"

Usa "alertas" para ver alertas activas."""
    
    async def _show_active_alerts(self, tenant_id: str) -> str:
        """Show active alerts and their configuration"""
        try:
            # Get all alert configs for tenant
            result = self.db.table("alert_configs").select("*").eq(
                "tenant_id", tenant_id
            ).execute()
            
            configs = result.data if result.data else []
            
            if not configs:
                return "No hay alertas configuradas. Usa 'configurar alertas' para configurarlas."
            
            message = "🔔 *Alertas Configuradas:*\n\n"
            
            for config_data in configs:
                config = AlertConfig.from_dict(config_data)
                status = "✅ Activada" if config.enabled else "❌ Desactivada"
                
                message += f"*{config.alert_type.value.replace('_', ' ').title()}*\n"
                message += f"Estado: {status}\n"
                
                if config.threshold:
                    message += f"Umbral: {config.threshold}\n"
                
                if config.last_triggered:
                    if isinstance(config.last_triggered, datetime):
                        last_time = config.last_triggered.strftime("%d/%m %H:%M")
                    else:
                        try:
                            last_time = datetime.fromisoformat(config.last_triggered).strftime("%d/%m %H:%M")
                        except (ValueError, TypeError):
                            last_time = "Fecha inválida"
                    message += f"Última alerta: {last_time}\n"
                
                message += "\n"
            
            return message
            
        except Exception as e:
            logger.error(f"Error showing active alerts: {e}")
            return "Error al mostrar alertas configuradas."
    
    async def _get_frequent_questions(self, tenant_id: str) -> str:
        """Get most frequent customer questions"""
        try:
            # Get frequent questions from conversation analytics
            result = self.db.table("conversation_analytics").select(
                "topic, COUNT(*) as count"
            ).eq("tenant_id", tenant_id).not_.eq("topic", None).group_by(
                "topic"
            ).order("count", desc=True).limit(5).execute()
            
            if not result.data:
                return "No hay datos de preguntas frecuentes aún."
            
            message = "❓ *Preguntas Frecuentes de Clientes:*\n\n"
            
            for i, item in enumerate(result.data, 1):
                topic = item["topic"] or "Sin tema"
                count = item["count"]
                message += f"{i}. {topic}: {count} veces\n"
            
            message += "\nUsa 'analytics' para ver más detalles."
            return message
            
        except Exception as e:
            logger.error(f"Error getting frequent questions: {e}")
            return "Error al obtener preguntas frecuentes."
    
    async def _get_configuration_menu(self, tenant_id: str) -> str:
        """Show configuration menu"""
        return """⚙️ *Configuración del Bot*

Configura tu bot de WhatsApp:

1️⃣ *Horarios* - Configura horarios de atención
   Comando: "configurar horarios [inicio] [fin]"
   Ejemplo: "configurar horarios 9:00 21:00"

2️⃣ *Modo offline* - Configura respuestas cuando estés offline
   Comando: "activar modo offline" o "desactivar modo offline"

3️⃣ *Pausar bot* - Pausa temporalmente el bot
   Comando: "pausar bot" o "reanudar bot"

4️⃣ *Alertas* - Configura alertas inteligentes
   Comando: "configurar alertas"

5️⃣ *Productos* - Gestiona productos y precios
   Comando: "agregar producto" o "actualizar precios"

¿Qué deseas configurar?"""
    
    async def _get_dashboard_menu(self) -> str:
        """Show main dashboard menu"""
        return """📊 *Dashboard Conversacional*

Bienvenido al panel de control por WhatsApp:

📈 *Métricas y Análisis*
• "resumen" - Resumen del día con ventas y pedidos
• "analytics" - Análisis de conversaciones y tendencias
• "preguntas frecuentes" - Preguntas más comunes de clientes

📦 *Inventario y Stock*
• "stock" - Estado actual del inventario
• "actualizar stock [producto] [cantidad]" - Actualizar stock
• "configurar alertas stock [umbral]" - Configurar alertas de stock bajo

🔔 *Alertas Inteligentes*
• "alertas" - Ver alertas activas
• "configurar alertas" - Configurar alertas inteligentes

⚙️ *Configuración*
• "config" - Configuración del bot y horarios

¿En qué puedo ayudarte?"""


# Global instance for convenience (created on demand)
_conversational_dashboard_instance = None

def get_conversational_dashboard():
    """Get or create global ConversationalDashboard instance"""
    global _conversational_dashboard_instance
    if _conversational_dashboard_instance is None:
        _conversational_dashboard_instance = ConversationalDashboard()
    return _conversational_dashboard_instance