"""
Alert Scheduler Service for Vendly Pro
Periodically checks and sends smart alerts to sellers
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
import signal
import sys

from db.supabase import get_supabase_client
from db.whatsapp_config import fetch_config
from services.whatsapp.meta_service import MetaWhatsAppService
from services.conversational_dashboard import ConversationalDashboard

logger = logging.getLogger(__name__)


class AlertScheduler:
    """Schedules and sends smart alerts to sellers"""
    
    def __init__(self, check_interval_minutes: int = 30):
        self.db = get_supabase_client()
        self.whatsapp_service = MetaWhatsAppService()
        self.dashboard = ConversationalDashboard(self.db)
        self.check_interval = check_interval_minutes * 60  # Convert to seconds
        self.running = False
        
    async def start(self):
        """Start the alert scheduler"""
        self.running = True
        logger.info(f"Alert scheduler started with {self.check_interval/60} minute interval")
        
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        try:
            while self.running:
                await self._check_all_tenants()
                await asyncio.sleep(self.check_interval)
        except asyncio.CancelledError:
            logger.info("Alert scheduler cancelled")
        except Exception as e:
            logger.error(f"Error in alert scheduler: {e}")
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the alert scheduler"""
        self.running = False
        logger.info("Alert scheduler stopped")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
    async def _check_all_tenants(self):
        """Check alerts for all active tenants"""
        try:
            # Get all active tenants with conversational dashboard enabled
            tenants_result = self.db.table("tenant_subscriptions").select(
                "tenant_id, plan_type, features"
            ).eq("status", "active").execute()
            
            if not tenants_result.data:
                logger.info("No active tenants found")
                return
            
            tenants = tenants_result.data
            logger.info(f"Checking alerts for {len(tenants)} tenants")
            
            for tenant_sub in tenants:
                tenant_id = tenant_sub["tenant_id"]
                features = tenant_sub.get("features", {})
                
                # Check if conversational dashboard is enabled for this tenant
                if not features.get("conversational_dashboard", False):
                    continue
                
                try:
                    await self._check_tenant_alerts(tenant_id)
                except Exception as e:
                    logger.error(f"Error checking alerts for tenant {tenant_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Error checking all tenants: {e}")
    
    async def _check_tenant_alerts(self, tenant_id: str):
        """Check and send alerts for a specific tenant"""
        try:
            # Get tenant configuration
            tenant_result = self.db.table("tenants").select(
                "id, name"
            ).eq("id", tenant_id).execute()
            
            if not tenant_result.data:
                logger.warning(f"Tenant {tenant_id} not found")
                return
            
            tenant = tenant_result.data[0]
            
            # Get seller phone number from WhatsApp config
            config = fetch_config(self.db, tenant_id, "seller_phone, phone_number")

            if not config:
                logger.warning(f"WhatsApp config not found for tenant {tenant_id}")
                return

            seller_phone = config.get("seller_phone") or config.get("phone_number")
            
            if not seller_phone:
                logger.warning(f"No seller phone found for tenant {tenant_id}")
                return
            
            # Check alerts using ConversationalDashboard
            alerts = await self.dashboard.check_and_send_alerts(tenant_id)
            
            if not alerts:
                logger.debug(f"No alerts for tenant {tenant_id}")
                return
            
            # Send each alert via WhatsApp
            for alert_message in alerts:
                if alert_message:
                    await self._send_alert_to_seller(
                        tenant_id=tenant_id,
                        seller_phone=seller_phone,
                        alert_message=alert_message,
                        tenant_name=tenant.get("name", "Tienda")
                    )
                    
        except Exception as e:
            logger.error(f"Error checking tenant alerts {tenant_id}: {e}")
    
    async def _send_alert_to_seller(
        self, 
        tenant_id: str, 
        seller_phone: str, 
        alert_message: str,
        tenant_name: str
    ):
        """Send alert message to seller via WhatsApp"""
        try:
            # Get WhatsApp phone number ID for this tenant
            config = fetch_config(self.db, tenant_id, "phone_number_id, access_token")

            if not config:
                logger.error(f"WhatsApp config not found for tenant {tenant_id}")
                return

            phone_number_id = config.get("phone_number_id")
            access_token = config.get("access_token")

            if not phone_number_id:
                logger.error(f"No phone_number_id found for tenant {tenant_id}")
                return

            # Credentials go to the constructor and send_message takes only
            # (to, message). This used to pass phone_number_id= as a keyword and
            # await the result, so every call raised TypeError twice over -
            # send_message is synchronous and has no such parameter. No seller
            # alert had ever been delivered.
            #
            # Built per tenant rather than reusing self.whatsapp_service, which
            # was constructed with no arguments and therefore fell back to the
            # global META_WHATSAPP_PHONE_ID - the wrong number for every tenant
            # but one.
            whatsapp_service = MetaWhatsAppService(
                phone_number_id=phone_number_id,
                access_token=access_token,
            )

            # requests.post blocks; off the loop so a 30s timeout cannot stall
            # the scheduler.
            result = await asyncio.to_thread(
                whatsapp_service.send_message, seller_phone, alert_message
            )
            success = result.get("status") == "sent"

            if not success:
                logger.error(
                    "Alert to %s failed for tenant %s: %s",
                    seller_phone, tenant_id, result.get("error"),
                )

            if success:
                logger.info(f"Alert sent to seller {seller_phone} for tenant {tenant_name}")
                
                # Log the alert in database
                await self._log_alert_sent(
                    tenant_id=tenant_id,
                    seller_phone=seller_phone,
                    alert_message=alert_message
                )
            else:
                logger.error(f"Failed to send alert to seller {seller_phone}")
                
        except Exception as e:
            logger.error(f"Error sending alert to seller: {e}")
    
    async def _log_alert_sent(self, tenant_id: str, seller_phone: str, alert_message: str):
        """Log alert sent to database"""
        try:
            log_data = {
                "tenant_id": tenant_id,
                "seller_phone": seller_phone,
                "alert_type": self._extract_alert_type(alert_message),
                "message": alert_message[:500],  # Truncate if too long
                "sent_at": datetime.now().isoformat(),
                "status": "sent"
            }
            
            self.db.table("alert_logs").insert(log_data).execute()
            
        except Exception as e:
            logger.error(f"Error logging alert: {e}")
    
    def _extract_alert_type(self, alert_message: str) -> str:
        """Extract alert type from message"""
        if "ALERTA: Stock Bajo" in alert_message:
            return "low_stock"
        elif "ALERTA: Cliente VIP" in alert_message:
            return "vip_customer"
        elif "ALERTA: Anomalía en Ventas" in alert_message:
            return "sales_anomaly"
        elif "ALERTA: Feedback Negativo" in alert_message:
            return "negative_feedback"
        else:
            return "unknown"


# Global instance
alert_scheduler = AlertScheduler()


async def start_alert_scheduler():
    """Start the alert scheduler service"""
    scheduler = AlertScheduler()
    await scheduler.start()


if __name__ == "__main__":
    # For running as standalone script
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger.info("Starting alert scheduler...")
    
    try:
        asyncio.run(start_alert_scheduler())
    except KeyboardInterrupt:
        logger.info("Alert scheduler stopped by user")
    except Exception as e:
        logger.error(f"Alert scheduler failed: {e}")
        sys.exit(1)