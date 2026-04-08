"""
Seller message handlers for WhatsApp bot
"""
from typing import Dict, Any, Optional
import logging
from datetime import datetime

from .base import BaseWhatsAppHandler

logger = logging.getLogger(__name__)

class SellerMenuHandler(BaseWhatsAppHandler):
    """Handles seller menu and commands"""
    
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """Check if user is seller and message is a command"""
        is_seller = message_data.get("is_seller", False)
        message = message_data.get("message", "").lower().strip()
        
        return is_seller and any(
            cmd in message 
            for cmd in ["pedidos", "órdenes", "stock", "inventario", "actualizar", "resumen", "estadísticas"]
        )
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Handle seller commands"""
        tenant_id = message_data.get("tenant_id")
        message = message_data.get("message", "").lower().strip()
        
        if "pedidos" in message or "órdenes" in message:
            return await self._send_orders_summary(tenant_id)
        elif "stock" in message or "inventario" in message:
            if "actualizar" in message:
                return await self._process_stock_update(tenant_id, message)
            else:
                return await self._send_stock_status(tenant_id)
        elif "resumen" in message or "estadísticas" in message:
            return await self._send_daily_summary(tenant_id)
        else:
            return await self._send_seller_menu()
    
    async def _send_orders_summary(self, tenant_id: str) -> str:
        """Send orders summary to seller"""
        try:
            # Get today's orders
            today = datetime.now().date().isoformat()
            orders_result = self.db.table("orders").select("*").eq(
                "tenant_id", tenant_id
            ).gte("created_at", today).execute()
            
            if not orders_result.data:
                return "No tienes pedidos hoy."
            
            orders = orders_result.data
            completed_orders = [o for o in orders if o["status"] == "completed"]
            pending_orders = [o for o in orders if o["status"] in ["pending", "payment_pending"]]
            
            total_revenue = sum(o["total"] for o in completed_orders)
            
            message = f"""📊 *Resumen del Día ({today})*

✅ Pedidos completados: {len(completed_orders)}
💰 Ingresos: ${total_revenue:.2f}

⏳ Pedidos pendientes: {len(pending_orders)}

¿Qué deseas hacer?
1️⃣ Ver pedidos pendientes
2️⃣ Consultar stock
3️⃣ Ver productos más vendidos"""
            
            return message
            
        except Exception as e:
            logger.error(f"Error getting orders summary: {e}")
            return "Error al obtener resumen de pedidos."
    
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
    
    async def _process_stock_update(self, tenant_id: str, message: str) -> str:
        """Process stock update command"""
        try:
            # Parse message: "actualizar stock [producto] [cantidad]"
            parts = message.split()
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
    
    async def _send_daily_summary(self, tenant_id: str) -> str:
        """Send daily summary to seller"""
        try:
            # Get last 7 days data
            start_date = (datetime.now() - datetime.timedelta(days=7)).date().isoformat()
            
            orders_result = self.db.table("orders").select(
                "created_at, total, status"
            ).eq("tenant_id", tenant_id).gte("created_at", start_date).execute()
            
            if not orders_result.data:
                return "No hay pedidos en los últimos 7 días."
            
            total_revenue = 0
            total_orders = len(orders_result.data)
            completed_orders = 0
            
            for order in orders_result.data:
                if order["status"] in ["completed", "delivered"]:
                    total_revenue += float(order.get("total", 0) or 0)
                    completed_orders += 1
            
            message = f"""📈 *Resumen de 7 días*

📊 Pedidos totales: {total_orders}
✅ Completados: {completed_orders}
💰 Ingresos: ${total_revenue:.2f}
📈 Tasa de completado: {(completed_orders/total_orders*100):.1f}%

Usa "pedidos" para ver detalles o "stock" para inventario."""
            
            return message
            
        except Exception as e:
            logger.error(f"Error getting daily summary: {e}")
            return "Error al obtener resumen diario."
    
    async def _send_seller_menu(self) -> str:
        """Send seller menu"""
        return """🛠️ *Panel de Vendedor*

¿Qué necesitas hacer?
• Escribe "pedidos" - Ver resumen de pedidos
• Escribe "stock" - Consultar inventario
• Escribe "actualizar stock [producto] [cantidad]" - Actualizar stock
• Escribe "resumen" - Ver estadísticas del día"""
