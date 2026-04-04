from typing import Dict, Any, Optional
import re
import json
import httpx
from datetime import datetime
from db.supabase import get_supabase_client
from api.v1.whatsapp import WhatsAppMessage
from api.v1.cart import get_cart as get_cart_service
from config import get_settings

class WhatsAppBotService:
    def __init__(self):
        self.db = get_supabase_client()
        settings = get_settings()
        self.evolution_api_url = settings.EVOLUTION_API_URL
        self.evolution_api_key = settings.EVOLUTION_API_KEY
    
    async def process_message(self, sender: str, message: str, instance_id: str):
        """Procesar mensaje entrante y generar respuesta"""
        
        # Identificar tenant por instance_id
        tenant = await self.get_tenant_by_instance(instance_id)
        if not tenant:
            return
        
        tenant_id = tenant["id"]
        tenant_name = tenant.get("name", "Tienda")
        
        # Obtener o crear sesión de conversación
        session = await self.get_or_create_session(tenant_id, sender, instance_id)
        
        # Identificar si es vendedor o cliente
        is_seller = await self.is_seller(tenant_id, sender)
        
        if is_seller:
            await self.process_seller_message(tenant_id, sender, message, instance_id, session)
        else:
            await self.process_customer_message(tenant_id, sender, message, instance_id, session, tenant_name)
    
    async def process_customer_message(self, tenant_id: str, sender: str, message: str, instance_id: str, session: Dict, tenant_name: str):
        """Procesar mensaje de cliente"""
        
        current_state = session.get("current_state", "initial")
        message_lower = message.lower().strip()
        
        # Estado inicial
        if current_state == "initial":
            if "hola" in message_lower or "hi" in message_lower:
                await self.send_welcome_message(tenant_id, sender, instance_id, tenant_name)
                await self.update_session_state(session["id"], "initial")
            
            elif "pedido:" in message_lower:
                # Cliente viene del storefront con un carrito
                cart_id = message_lower.replace("pedido:", "").strip()
                await self.process_cart_from_storefront(tenant_id, sender, cart_id, instance_id, session)
            
            elif "menu" in message_lower or "catálogo" in message_lower or "ver productos" in message_lower:
                await self.send_menu(tenant_id, sender, instance_id)
            
            else:
                await self.send_welcome_message(tenant_id, sender, instance_id, tenant_name)
        
        # Estado viendo carrito
        elif current_state == "viewing_cart":
            if "sí" in message_lower or "si" in message_lower or "confirmo" in message_lower:
                await self.confirm_order(tenant_id, sender, instance_id, session)
            elif "agregar" in message_lower or "añadir" in message_lower:
                await self.ask_for_addition(tenant_id, sender, instance_id)
            elif "cancelar" in message_lower:
                await self.cancel_order(tenant_id, sender, instance_id, session)
            else:
                await self.ask_for_confirmation(tenant_id, sender, instance_id)
        
        # Estado de pago pendiente
        elif current_state == "payment_pending":
            # Esperando comprobante de pago
            if message_lower.startswith("https://") or message_lower.startswith("http://"):
                # Es una URL de imagen (comprobante)
                await self.process_payment_proof(tenant_id, sender, message, instance_id, session)
            else:
                await self.request_payment_proof(tenant_id, sender, instance_id)
    
    async def process_seller_message(self, tenant_id: str, sender: str, message: str, instance_id: str, session: Dict):
        """Procesar mensaje de vendedor"""
        
        message_lower = message.lower().strip()
        
        # Comandos del vendedor
        if "pedidos" in message_lower or "órdenes" in message_lower:
            await self.send_orders_summary(tenant_id, sender, instance_id)
        
        elif "stock" in message_lower or "inventario" in message_lower:
            await self.send_stock_status(tenant_id, sender, instance_id)
        
        elif "actualizar" in message_lower and "stock" in message_lower:
            await self.process_stock_update(tenant_id, sender, message, instance_id)
        
        elif "resumen" in message_lower or "estadísticas" in message_lower:
            await self.send_daily_summary(tenant_id, sender, instance_id)
        
        else:
            await self.send_seller_menu(tenant_id, sender, instance_id)
    
    async def process_cart_from_storefront(self, tenant_id: str, sender: str, cart_id: str, instance_id: str, session: Dict):
        """Procesar carrito desde storefront"""
        
        try:
            # Obtener carrito desde Redis
            cart = await get_cart_service(cart_id)
            
            if not cart:
                await self.send_message(instance_id, sender, "El carrito ha expirado. Por favor, crea uno nuevo desde la tienda.")
                return
            
            # Actualizar sesión con carrito
            await self.update_session_data(session["id"], {"cart_id": cart_id})
            await self.update_session_state(session["id"], "viewing_cart")
            
            # Enviar resumen del carrito
            await self.send_cart_summary(tenant_id, sender, cart, instance_id)
            
        except Exception as e:
            await self.send_message(instance_id, sender, "No puedo encontrar tu carrito. Por favor, intenta nuevamente.")
    
    async def send_cart_summary(self, tenant_id: str, sender: str, cart: Dict, instance_id: str):
        """Enviar resumen del carrito al cliente"""
        
        items_text = "\n".join([
            f"{item['quantity']}x {item['name']} - ${item['price'] * item['quantity']:.2f}"
            for item in cart["items"]
        ])
        
        message = f"""¡Hola! Soy el asistente de Vendly.

Tu pedido:
{items_text}

Total: ${cart['total']:.2f}

¿Deseas agregar algo más o confirmar el pedido?"""
        
        await self.send_message(instance_id, sender, message)
    
    async def confirm_order(self, tenant_id: str, sender: str, instance_id: str, session: Dict):
        """Confirmar pedido y enviar instrucciones de pago"""
        
        # Obtener configuración de pago
        bot_config = await self.get_bot_configuration(tenant_id)
        payment_info = bot_config.get("payment_info", {})
        
        # Obtener carrito
        cart_id = session.get("session_data", {}).get("cart_id")
        if not cart_id:
            await self.send_message(instance_id, sender, "No encuentro tu carrito. Por favor, inicia nuevamente.")
            return
        
        cart = await get_cart_service(cart_id)
        if not cart:
            await self.send_message(instance_id, sender, "Tu carrito ha expirado. Por favor, crea uno nuevo.")
            return
        
        # Crear pedido en base de datos
        order_data = {
            "tenant_id": tenant_id,
            "customer_phone": sender,
            "total": cart["total"],
            "status": "payment_pending",
            "source": "whatsapp",
            "items": cart["items"]
        }
        
        order_result = self.db.table("orders").insert(order_data).execute()
        order = order_result.data[0] if order_result.data else None
        
        if not order:
            await self.send_message(instance_id, sender, "Error al procesar tu pedido. Por favor, intenta nuevamente.")
            return
        
        # Enviar instrucciones de pago
        payment_message = f"""¡Pedido confirmado! 🎉

Orden #{order['id'][-8:]}  # Últimos 8 dígitos

Total: ${cart['total']:.2f}

💳 Datos para Pago Móvil:
Banco: {payment_info.get('bank', 'Banesco')}
CI: {payment_info.get('ci', 'V-12345678')}
Teléfono: {payment_info.get('phone', '0412-XXX-XXXX')}
Monto: ${cart['total']:.2f}

Por favor, envía el comprobante de pago cuando hayas realizado la transferencia."""
        
        await self.send_message(instance_id, sender, payment_message)
        
        # Notificar al vendedor
        await self.notify_seller_new_order(tenant_id, order, instance_id)
        
        # Actualizar estado de sesión
        await self.update_session_state(session["id"], "payment_pending")
        await self.update_session_data(session["id"], {"order_id": order["id"]})
    
    async def notify_seller_new_order(self, tenant_id: str, order: Dict, instance_id: str):
        """Notificar al vendedor sobre nuevo pedido"""
        
        # Obtener conexión WhatsApp del vendedor
        connection = self.db.table("whatsapp_connections").select("*").eq("tenant_id", tenant_id).eq("status", "connected").execute()
        
        if not connection.data:
            return
        
        seller_number = connection.data[0]["phone_number"]
        
        # Formatear mensaje para vendedor
        items_text = "\n".join([
            f"{item['quantity']}x {item['name']}" 
            for item in order["items"]
        ])
        
        message = f"""💰 Nuevo pedido recibido

Cliente: {order['customer_phone']}
Orden: #{order['id'][-8:]}
Total: ${order['total']:.2f}

Items:
{items_text}

Estado: Esperando pago

Responde 'confirmar #{order['id'][-8:]}' para confirmar el pago cuando lo recibas."""
        
        await self.send_message(instance_id, seller_number, message)
    
    async def send_welcome_message(self, tenant_id: str, sender: str, instance_id: str, tenant_name: str):
        """Enviar mensaje de bienvenida"""
        
        bot_config = await self.get_bot_configuration(tenant_id)
        welcome_msg = bot_config.get("welcome_message", "¡Hola! Soy el asistente de {store_name}. ¿En qué puedo ayudarte?")
        
        message = welcome_msg.format(store_name=tenant_name)
        
        # Agregar opciones rápidas
        message += """

🛒 *Opciones:*
• Escribe "menu" para ver nuestros productos
• Escribe "pedido:TU_CARRO_ID" si vienes de la web
• Escribe "hola" para empezar"""
        
        await self.send_message(instance_id, sender, message)
    
    async def send_menu(self, tenant_id: str, sender: str, instance_id: str):
        """Enviar menú de productos"""
        
        # Obtener productos destacados
        items_result = self.db.table("items").select("name, price, description").eq("tenant_id", tenant_id).eq("is_active", True).eq("is_featured", True).limit(5).execute()
        
        if not items_result.data:
            await self.send_message(instance_id, sender, "No hay productos disponibles en este momento.")
            return
        
        items_text = "\n\n".join([
            f"🍔 {item['name']}\n💲 ${item['price']:.2f}\n{item.get('description', '')}"
            for item in items_result.data
        ])
        
        message = f"""📋 *Nuestros Productos Destacados:*

{items_text}

🛍️ Para ordenar, visita nuestra tienda o escríbeme lo que deseas."""
        
        await self.send_message(instance_id, sender, message)
    
    async def send_orders_summary(self, tenant_id: str, sender: str, instance_id: str):
        """Enviar resumen de pedidos al vendedor"""
        
        # Obtener pedidos del día
        today = datetime.now().date().isoformat()
        orders_result = self.db.table("orders").select("*").eq("tenant_id", tenant_id).gte("created_at", today).execute()
        
        if not orders_result.data:
            await self.send_message(instance_id, sender, "No tienes pedidos hoy.")
            return
        
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
        
        await self.send_message(instance_id, sender, message)
    
    async def send_stock_status(self, tenant_id: str, sender: str, instance_id: str):
        """Enviar estado de stock al vendedor"""
        
        # Obtener productos con stock bajo
        items_result = self.db.table("items").select("name, stock_quantity").eq("tenant_id", tenant_id).eq("is_active", True).eq("track_stock", True).execute()
        
        if not items_result.data:
            await self.send_message(instance_id, sender, "No hay productos con control de stock.")
            return
        
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
            for item in normal_stock_items[:5]:  # Limitar a 5 para no sobrecargar
                message += f"• {item['name']}: {item['stock_quantity']} unidades\n"
        
        await self.send_message(instance_id, sender, message)
    
    async def send_seller_menu(self, tenant_id: str, sender: str, instance_id: str):
        """Enviar menú de vendedor"""
        
        message = """🛠️ *Panel de Vendedor*

¿Qué necesitas hacer?
• Escribe "pedidos" - Ver resumen de pedidos
• Escribe "stock" - Consultar inventario
• Escribe "actualizar stock [producto] [cantidad]" - Actualizar stock
• Escribe "resumen" - Ver estadísticas del día"""
        
        await self.send_message(instance_id, sender, message)
    
    # Métodos auxiliares
    async def send_message(self, instance_id: str, to: str, message: str):
        """Enviar mensaje vía Evolution API"""
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.evolution_api_url}/message/sendText/{instance_id}",
                    headers={"apikey": self.evolution_api_key},
                    json={
                        "number": to,
                        "text": message
                    }
                )
                
                # Guardar en log de mensajes
                await self.log_message(instance_id, to, message, "outbound", response.status_code == 200)
                
        except Exception as e:
            print(f"Error sending message: {e}")
    
    async def get_tenant_by_instance(self, instance_id: str) -> Optional[Dict]:
        """Obtener tenant por instance_id"""
        
        result = self.db.table("whatsapp_connections").select("tenant_id, name").eq("instance_id", instance_id).eq("status", "connected").execute()
        
        if result.data:
            tenant_id = result.data[0]["tenant_id"]
            tenant_result = self.db.table("tenants").select("id, name").eq("id", tenant_id).execute()
            return tenant_result.data[0] if tenant_result.data else None
        
        return None
    
    async def get_or_create_session(self, tenant_id: str, sender: str, instance_id: str) -> Dict:
        """Obtener o crear sesión de conversación"""
        
        # Buscar sesión existente
        result = self.db.table("conversation_sessions").select("*").eq("tenant_id", tenant_id).eq("customer_phone", sender).eq("instance_id", instance_id).execute()
        
        if result.data:
            session = result.data[0]
            # Actualizar último mensaje
            self.db.table("conversation_sessions").update({
                "last_message_at": datetime.now().isoformat()
            }).eq("id", session["id"]).execute()
            return session
        
        # Crear nueva sesión
        session_data = {
            "tenant_id": tenant_id,
            "customer_phone": sender,
            "instance_id": instance_id,
            "current_state": "initial"
        }
        
        result = self.db.table("conversation_sessions").insert(session_data).execute()
        return result.data[0] if result.data else {}
    
    async def update_session_state(self, session_id: str, new_state: str):
        """Actualizar estado de sesión"""
        
        self.db.table("conversation_sessions").update({
            "current_state": new_state,
            "updated_at": datetime.now().isoformat()
        }).eq("id", session_id).execute()
    
    async def update_session_data(self, session_id: str, data: Dict):
        """Actualizar datos de sesión"""
        
        self.db.table("conversation_sessions").update({
            "session_data": data,
            "updated_at": datetime.now().isoformat()
        }).eq("id", session_id).execute()
    
    async def get_bot_configuration(self, tenant_id: str) -> Dict:
        """Obtener configuración del bot"""
        
        result = self.db.table("bot_configurations").select("*").eq("tenant_id", tenant_id).execute()
        
        if result.data:
            return result.data[0]
        
        # Configuración por defecto
        return {
            "welcome_message": "¡Hola! Soy el asistente de {store_name}. ¿En qué puedo ayudarte?",
            "payment_info": {
                "bank": "Banesco",
                "ci": "V-12345678",
                "phone": "0412-XXX-XXXX"
            }
        }
    
    async def is_seller(self, tenant_id: str, phone: str) -> bool:
        """Verificar si es número de vendedor"""
        
        # Verificar si está en conexiones WhatsApp
        result = self.db.table("whatsapp_connections").select("*").eq("tenant_id", tenant_id).eq("phone_number", phone).execute()
        return len(result.data) > 0
    
    async def log_message(self, instance_id: str, phone: str, content: str, direction: str, success: bool):
        """Guardar mensaje en log"""
        
        try:
            message_data = {
                "instance_id": instance_id,
                "sender_phone": phone if direction == "inbound" else "bot",
                "receiver_phone": "bot" if direction == "inbound" else phone,
                "message_type": "text",
                "content": content,
                "direction": direction,
                "status": "delivered" if success else "failed"
            }
            
            self.db.table("whatsapp_messages").insert(message_data).execute()
        except Exception as e:
            print(f"Error logging message: {e}")

# Instancia global del servicio
bot_service = WhatsAppBotService()
