"""
Conversational Onboarding Handler for WhatsApp Bot

Implements step-by-step WhatsApp-guided setup for new tenants including:
- Business configuration
- Product upload via photos and descriptions
- Business hours and service parameters
"""
from typing import Dict, Any, Optional, List
import logging
import re
from datetime import datetime

from .base import BaseWhatsAppHandler
from services.bot_personalities import PRESETS, default_preset_for_industry, preset_names
from services.multi_tenant_orchestrator import MultiTenantOrchestrator
from services.offline_mode_service import OfflineModeService, parse_weekly_schedule

logger = logging.getLogger(__name__)

# International phone format, shared by the business number and the owner's
# personal alert number.
PHONE_RE = r'^\+?[1-9]\d{1,14}$'


class OnboardingState:
    """States for the onboarding flow"""
    START = "onboarding_start"
    BUSINESS_INFO = "onboarding_business_info"
    INDUSTRY_SELECTION = "onboarding_industry_selection"
    BUSINESS_HOURS = "onboarding_business_hours"
    PERSONALITY = "onboarding_personality"
    PRODUCT_UPLOAD = "onboarding_product_upload"
    PRODUCT_DESCRIPTION = "onboarding_product_description"
    PRODUCT_PHOTO = "onboarding_product_photo"
    PRODUCT_CONFIRMATION = "onboarding_product_confirmation"
    COMPLETED = "onboarding_completed"


class OnboardingHandler(BaseWhatsAppHandler):
    """Handles conversational onboarding for new tenants"""
    
    def __init__(self, db_client, next_handler=None):
        super().__init__(db_client, next_handler)
        self._onboarding_sessions: Dict[str, Dict[str, Any]] = {}
    
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """Check if message should be handled by onboarding"""
        tenant_id = message_data.get("tenant_id")
        message = message_data.get("message", "").lower().strip()
        session = message_data.get("session", {})
        
        # Check if tenant is in onboarding mode
        is_onboarding = await self._is_tenant_in_onboarding(tenant_id)
        
        # Check if message triggers onboarding
        triggers = ["configurar", "configuración", "config", "empezar", "dar de alta", "alta", "registrarse", "registro"]
        
        return is_onboarding and any(trigger in message for trigger in triggers)
    
    async def _is_tenant_in_onboarding(self, tenant_id: str) -> bool:
        """Check if tenant is currently in onboarding flow"""
        try:
            result = self.db.table("tenants").select("onboarding_status").eq("id", tenant_id).execute()
            if result.data and result.data[0]:
                status = result.data[0].get("onboarding_status", "not_started")
                return status in ["in_progress", "not_started"]
            return False
        except Exception as e:
            logger.error(f"Error checking onboarding status: {e}")
            return False
    
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Handle onboarding messages"""
        tenant_id = message_data.get("tenant_id")
        phone = message_data.get("phone")
        # Kept as typed. The business name, description and product names are
        # content, not keywords, and folding the whole message to lowercase
        # stored "El Sabor de Maria" as "el sabor de maria". Every handler that
        # matches keywords lowercases on its own, and both free-text parsers
        # (parse_weekly_schedule, _parse_product_info) are already
        # case-insensitive, so nothing downstream relied on it happening here.
        message = message_data.get("message", "").strip()
        session = message_data.get("session", {})
        
        # Get or create onboarding session
        session_id = session.get("id")
        onboarding_data = await self._get_onboarding_session(tenant_id, phone)
        
        # Determine current state
        current_state = onboarding_data.get("current_state", OnboardingState.START)
        
        # Process based on state
        if current_state == OnboardingState.START:
            return await self._handle_start(tenant_id, phone, message, onboarding_data)
        elif current_state == OnboardingState.INDUSTRY_SELECTION:
            return await self._handle_industry_selection(tenant_id, phone, message, onboarding_data)
        elif current_state == OnboardingState.BUSINESS_INFO:
            return await self._handle_business_info(tenant_id, phone, message, onboarding_data)
        elif current_state == OnboardingState.BUSINESS_HOURS:
            return await self._handle_business_hours(tenant_id, phone, message, onboarding_data)
        elif current_state == OnboardingState.PERSONALITY:
            return await self._handle_personality(tenant_id, phone, message, onboarding_data)
        elif current_state == OnboardingState.PRODUCT_UPLOAD:
            return await self._handle_product_upload(tenant_id, phone, message, onboarding_data)
        elif current_state == OnboardingState.PRODUCT_DESCRIPTION:
            return await self._handle_product_description(tenant_id, phone, message, onboarding_data)
        elif current_state == OnboardingState.PRODUCT_PHOTO:
            return await self._handle_product_photo(tenant_id, phone, message, onboarding_data)
        elif current_state == OnboardingState.PRODUCT_CONFIRMATION:
            return await self._handle_product_confirmation(tenant_id, phone, message, onboarding_data)
        else:
            return await self._handle_unknown_state(tenant_id, phone, message, onboarding_data)
    
    async def _handle_start(self, tenant_id: str, phone: str, message: str, onboarding_data: Dict) -> str:
        """Handle start of onboarding"""
        # Update session state
        await self._update_onboarding_state(tenant_id, phone, OnboardingState.INDUSTRY_SELECTION)
        
        return """🌟 *Bienvenido al Onboarding de Vendly Pro!*

Voy a ayudarte a configurar tu negocio paso a paso.

📋 *Paso 1: Tipo de Negocio*

¿Qué tipo de negocio tienes? Elige una opción:

1️⃣ *Restaurante* - Para restaurantes, cafeterías, food trucks
2️⃣ *Tienda Retail* - Para ropa, accesorios, productos
3️⃣ *Servicios* - Para servicios profesionales, consultoría, citas

Escribe el número (1, 2 o 3) o el nombre del tipo de negocio."""
    
    async def _handle_industry_selection(self, tenant_id: str, phone: str, message: str, onboarding_data: Dict) -> str:
        """Handle industry selection"""
        message_lower = message.lower().strip()
        
        # Map user input to industry types
        industry_map = {
            "1": "restaurant",
            "restaurante": "restaurant",
            "restaurant": "restaurant",
            "2": "retail",
            "tienda": "retail",
            "retail": "retail",
            "3": "services",
            "servicio": "services",
            "servicios": "services"
        }
        
        industry = industry_map.get(message_lower)
        
        if not industry:
            return """❌ Opción inválida.

Por favor, elige una opción válida:

1️⃣ *Restaurante* - Para restaurantes, cafeterías, food trucks
2️⃣ *Tienda Retail* - Para ropa, accesorios, productos
3️⃣ *Servicios* - Para servicios profesionales, consultoría, citas

Escribe el número (1, 2 o 3) o el nombre del tipo de negocio."""
        
        # Save industry selection in the session, and on the tenant itself:
        # tenants.type is what picks the default bot personality for the
        # industry (services/bot_personalities.py) and what the scheduling and
        # storefront code reads. Keeping it only in the session meant every
        # tenant stayed on whatever type it was created with.
        await self._update_onboarding_data(tenant_id, phone, {"industry": industry})
        await self._persist_tenant_fields(tenant_id, {"type": industry})

        # Move to next step
        await self._update_onboarding_state(tenant_id, phone, OnboardingState.BUSINESS_INFO)
        
        return f"""✅ *¡Perfecto! Has seleccionado: {industry.title()}*

📋 *Paso 2: Información del Negocio*

Necesito algunos datos básicos de tu negocio:

1️⃣ *Nombre del negocio* (ej: "El Sabor de Maria")
2️⃣ *Descripción breve* (ej: "Restaurante familiar con comida venezolana")
3️⃣ *Número de WhatsApp del negocio* (ej: +584123456789)
4️⃣ *Tu teléfono personal* (opcional) - donde querés recibir las alertas de tu negocio

Si no pones el cuarto, te enviamos las alertas al mismo número del negocio.

Ejemplo:
```
El Sabor de Maria
Restaurante familiar con comida venezolana auténtica
+584123456789
+584249876543
```"""
    
    async def _handle_business_info(self, tenant_id: str, phone: str, message: str, onboarding_data: Dict) -> str:
        """Handle business information input"""
        lines = message.strip().split("\n")
        
        if len(lines) < 3:
            return """📝 *Información incompleta.*

Por favor, envíame:
1️⃣ Nombre del negocio
2️⃣ Descripción breve
3️⃣ Número de WhatsApp del negocio
4️⃣ Tu teléfono personal (opcional)

Puedes enviarme esta información en un solo mensaje o en mensajes separados.

Ejemplo:
```
El Sabor de Maria
Restaurante familiar con comida venezolana auténtica
+584123456789
+584249876543
```"""

        # Parse business info. The 4th line is optional: it is the owner's own
        # phone, where business alerts go. Empty means "same as the business
        # number", which is what the seller_phone fallback already does.
        business_info = {
            "name": lines[0].strip(),
            "description": lines[1].strip() if len(lines) > 1 else "",
            "whatsapp_number": lines[2].strip() if len(lines) > 2 else "",
            "seller_phone": lines[3].strip() if len(lines) > 3 else ""
        }

        # Validate WhatsApp number format
        if not re.match(PHONE_RE, business_info.get("whatsapp_number", "")):
            return """❌ *Número de WhatsApp inválido.*

Por favor, envíame el número en formato internacional:
- Ejemplo: +584123456789
- Incluye el signo + y el código de país

Por favor, envía la información completa nuevamente."""

        if business_info["seller_phone"] and not re.match(PHONE_RE, business_info["seller_phone"]):
            return """❌ *Tu teléfono personal es inválido.*

Enviámelo en formato internacional (ej: +584249876543), o dejá la cuarta línea
vacía para recibir las alertas en el mismo número del negocio.

Por favor, envía la información completa nuevamente."""

        # Save business info in the session, and persist it. Until now these
        # three fields only ever lived in the session, so the name and
        # description the seller typed here went nowhere.
        await self._update_onboarding_data(tenant_id, phone, {"business_info": business_info})
        await self._persist_tenant_fields(tenant_id, {
            "name": business_info["name"],
            "description": business_info["description"],
            "whatsapp_number": business_info["whatsapp_number"],
        })

        if business_info["seller_phone"]:
            await self._persist_seller_phone(tenant_id, business_info["seller_phone"])

        # Move to next step
        await self._update_onboarding_state(tenant_id, phone, OnboardingState.BUSINESS_HOURS)

        alerts_line = business_info["seller_phone"] or f"{business_info['whatsapp_number']} (el mismo del negocio)"

        return f"""✅ *¡Información guardada!*

Nombre: {business_info['name']}
Descripción: {business_info['description']}
WhatsApp: {business_info['whatsapp_number']}
Alertas a: {alerts_line}

📋 *Paso 3: Horarios de Atención*

¿Cuáles son tus horarios de atención?

Por favor, envíame los horarios en este formato:

```
Lunes a Viernes: 11:00 AM - 10:00 PM
Sábado: 11:00 AM - 11:00 PM
Domingo: 12:00 PM - 9:00 PM
```"""
    
    async def _handle_business_hours(self, tenant_id: str, phone: str, message: str, onboarding_data: Dict) -> str:
        """Handle business hours configuration"""
        hours_data = parse_weekly_schedule(message)

        if not hours_data:
            return """❌ *Formato de horarios inválido.*

Por favor, envíame los horarios en este formato:

```
Lunes a Viernes: 11:00 AM - 10:00 PM
Sábado: 11:00 AM - 11:00 PM
Domingo: 12:00 PM - 9:00 PM
```

O si tienes horarios diferentes, envíame tu configuración y te ayudo a ajustarla."""

        # Save business hours (session, for display during onboarding) and
        # persist to bot_configurations.business_hours so scheduling/offline
        # mode actually see the hours the seller just configured.
        await self._update_onboarding_data(tenant_id, phone, {"business_hours": hours_data})
        await OfflineModeService(self.db).set_business_hours(
            tenant_id, hours_data, replace_week=True
        )
        
        # Move to next step
        await self._update_onboarding_state(tenant_id, phone, OnboardingState.PERSONALITY)

        industry = onboarding_data.get("industry")

        return f"""✅ *¡Horarios guardados!*

{self._format_business_hours(hours_data)}

{self._personality_prompt(industry)}"""

    def _personality_prompt(self, industry: Optional[str]) -> str:
        """The personality question, with the industry's default marked.

        Presented as a numbered list so answering takes one tap. Anything
        unrecognised accepts the suggestion rather than re-asking - this is a
        preference, not a required field.
        """
        suggested = default_preset_for_industry(industry)
        digits = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]

        options = []
        for index, name in enumerate(preset_names()):
            preset = PRESETS[name]
            mark = " ⭐ *(recomendado para tu rubro)*" if name == suggested else ""
            options.append(
                f"{digits[index]} *{preset['label']}*{mark}\n"
                f'   _"{preset["sample"]}"_'
            )

        return "📋 *Paso 4: ¿Cómo querés que hable tu bot?*\n\n" + "\n\n".join(options) + (
            "\n\nEscribe el número. Si no elegís, uso el recomendado."
        )

    async def _handle_personality(self, tenant_id: str, phone: str, message: str, onboarding_data: Dict) -> str:
        """Handle the bot personality choice."""
        choice = message.strip()
        names = preset_names()

        selected = None
        if choice.isdigit() and 1 <= int(choice) <= len(names):
            selected = names[int(choice) - 1]
        else:
            # Also accept the preset name itself, or its label.
            lowered = choice.lower()
            for name in names:
                if lowered == name or lowered == PRESETS[name]["label"].lower():
                    selected = name
                    break

        # No re-asking on an unrecognised answer: take the industry default and
        # move on, so a confused seller is never stuck on a preference.
        if selected is None:
            selected = default_preset_for_industry(onboarding_data.get("industry"))

        await self._update_onboarding_data(tenant_id, phone, {"bot_personality_preset": selected})
        await self._persist_tenant_fields(tenant_id, {"bot_personality_preset": selected})

        await self._update_onboarding_state(tenant_id, phone, OnboardingState.PRODUCT_UPLOAD)

        preset = PRESETS[selected]

        return f"""✅ *¡Listo! Tu bot va a hablar así:*

_"{preset['sample']}"_

📋 *Paso 5: Subir Productos*

¿Quieres subir productos ahora? Puedes hacerlo de dos formas:

1️⃣ *Por WhatsApp* - Envíame fotos y descripciones de tus productos
2️⃣ *Más tarde* - Puedes configurar tus productos desde el dashboard web

Escribe:
• "sí" o "subir productos" para comenzar
• "no" o "después" para configurar más tarde"""

    async def _persist_tenant_fields(self, tenant_id: str, fields: Dict[str, Any]) -> None:
        """Write onboarding answers onto the tenants row.

        Never raises: losing a field is worse than losing the whole
        conversation, but not worth dropping the seller out of onboarding.
        """
        try:
            self.db.table("tenants").update({
                **fields,
                "updated_at": datetime.now().isoformat(),
            }).eq("id", tenant_id).execute()
        except Exception as e:
            logger.error(
                f"Could not persist {sorted(fields)} for tenant {tenant_id}: {e}",
                exc_info=True,
            )

    async def _persist_seller_phone(self, tenant_id: str, seller_phone: str) -> None:
        """Store the owner's alert phone, reusing the orchestrator's upsert.

        whatsapp_configs may have no row yet at this point; set_seller_phone
        handles both cases and is the same call tenant creation makes.
        """
        try:
            orchestrator = MultiTenantOrchestrator()
            orchestrator.db = self.db
            await orchestrator.set_seller_phone(tenant_id, seller_phone)
        except Exception as e:
            logger.error(
                f"Could not persist seller phone for tenant {tenant_id}: {e}",
                exc_info=True,
            )


    async def _handle_product_upload(self, tenant_id: str, phone: str, message: str, onboarding_data: Dict) -> str:
        """Handle product upload decision"""
        message_lower = message.lower().strip()
        
        if any(word in message_lower for word in ["sí", "si", "subir", "productos", "subir productos"]):
            # Start product upload flow
            await self._update_onboarding_state(tenant_id, phone, OnboardingState.PRODUCT_DESCRIPTION)
            return """📸 *Subir Productos*

Voy a ayudarte a subir tus primeros productos.

📋 *Paso 4.1: Descripción del Producto*

Por favor, envíame la información de tu primer producto en este formato:

```
Nombre: Pizza Margarita
Precio: 15
Descripción: Pizza clásica con salsa de tomate, queso mozzarella y albahaca fresca
Categoría: Platos Principales
```

O simplemente envíame la información de forma natural, y yo la organizaré."""
        
        elif any(word in message_lower for word in ["no", "después", "luego", "mas tarde"]):
            # Skip product upload for now
            await self._complete_onboarding(tenant_id, phone)
            return """✅ *¡Onboarding completado!*

Puedes configurar tus productos más tarde desde el dashboard web o enviándome fotos por WhatsApp.

¿Necesitas ayuda con algo más?"""
        
        else:
            return """❓ *¿Quieres subir productos ahora?*

Escribe:
• "sí" o "subir productos" para comenzar
• "no" o "después" para configurar más tarde"""
    
    async def _handle_product_description(self, tenant_id: str, phone: str, message: str, onboarding_data: Dict) -> str:
        """Handle product description input"""
        product_info = self._parse_product_info(message)
        
        if not product_info.get("name") or not product_info.get("price"):
            return """❌ *Información de producto incompleta.*

Por favor, envíame:
1️⃣ *Nombre* del producto
2️⃣ *Precio* del producto
3️⃣ *Descripción* (opcional)
4️⃣ *Categoría* (opcional)

Ejemplo:
```
Nombre: Pizza Margarita
Precio: 15
Descripción: Pizza clásica con salsa de tomate, queso mozzarella y albahaca fresca
Categoría: Platos Principales
```

O envíame la información de forma natural."""
        
        # Save product info
        await self._update_onboarding_data(tenant_id, phone, {"current_product": product_info})
        
        # Move to photo upload
        await self._update_onboarding_state(tenant_id, phone, OnboardingState.PRODUCT_PHOTO)
        
        return f"""✅ *¡Información guardada!*

Nombre: {product_info['name']}
Precio: ${product_info['price']:.2f}
Descripción: {product_info.get('description', 'Sin descripción')}
Categoría: {product_info.get('category', 'Sin categoría')}

📸 *Paso 4.2: Foto del Producto*

Envíame una foto de este producto para que los clientes lo vean.

Puedes:
• Enviar una foto directamente por WhatsApp
• O escribir "saltar" si prefieres subir la foto más tarde"""
    
    async def _handle_product_photo(self, tenant_id: str, phone: str, message: str, onboarding_data: Dict) -> str:
        """Handle product photo upload"""
        message_lower = message.lower().strip()
        
        # Check if user wants to skip photo
        if any(word in message_lower for word in ["saltar", "no", "después"]):
            product_info = onboarding_data.get("current_product", {})
            await self._save_product(tenant_id, phone, product_info, photo_url=None)
            
            return await self._ask_continue_products(tenant_id, phone, onboarding_data)
        
        # Check if message contains a photo
        # Note: In a real implementation, we would check for message type "image"
        # For now, we'll assume the user has sent a photo if they don't respond with text
        if len(message.strip()) == 0 or message_lower in ["foto", "imagen", "enviado"]:
            product_info = onboarding_data.get("current_product", {})
            await self._save_product(tenant_id, phone, product_info, photo_url="user_sent_photo")
            
            return await self._ask_continue_products(tenant_id, phone, onboarding_data)
        
        # User sent text instead of photo, ask for photo
        return """📸 *Por favor, envíame una foto del producto.*

Puedes:
• Enviar una foto directamente por WhatsApp
• O escribir "saltar" si prefieres subir la foto más tarde"""
    
    async def _handle_product_confirmation(self, tenant_id: str, phone: str, message: str, onboarding_data: Dict) -> str:
        """Handle product confirmation"""
        message_lower = message.lower().strip()
        
        if any(word in message_lower for word in ["sí", "si", "confirmar", "acepto"]):
            # Product already saved in previous step
            return await self._ask_continue_products(tenant_id, phone, onboarding_data)
        
        elif any(word in message_lower for word in ["no", "cancelar", "rechazar"]):
            # Cancel current product
            await self._update_onboarding_data(tenant_id, phone, {"current_product": None})
            return """❌ *Producto cancelado.*

¿Quieres intentar con otro producto? Escribe:
• "sí" para subir otro producto
• "no" para terminar el onboarding"""
        
        else:
            return """❓ *¿Deseas confirmar este producto?*

Escribe:
• "sí" para confirmar y guardar el producto
• "no" para cancelar"""
    
    async def _ask_continue_products(self, tenant_id: str, phone: str, onboarding_data: Dict) -> str:
        """Ask if user wants to continue adding products"""
        return """✅ *¡Producto guardado!*

¿Quieres subir otro producto?

Escribe:
• "sí" para subir otro producto
• "no" para terminar el onboarding
• "resumen" para ver todos los productos subidos"""
    
    async def _complete_onboarding(self, tenant_id: str, phone: str) -> str:
        """Complete the onboarding process"""
        # Update tenant onboarding status
        try:
            self.db.table("tenants").update({
                "onboarding_status": "completed",
                "updated_at": datetime.now().isoformat()
            }).eq("id", tenant_id).execute()
            
            # Clear onboarding session
            self._onboarding_sessions.pop(f"{tenant_id}:{phone}", None)
            
            return """🎉 *¡Felicidades! Onboarding Completado*

Tu negocio está completamente configurado y listo para empezar a vender.

✅ *Configuración completada:*
• Tipo de negocio
• Información del negocio
• Horarios de atención
• Productos (si los subiste)

🚀 *Próximos pasos:*
1. Configura tu conexión con Meta WhatsApp
2. Empieza a recibir pedidos
3. Gestiona tu negocio desde WhatsApp

¿Necesitas ayuda con algo más?"""
        
        except Exception as e:
            logger.error(f"Error completing onboarding: {e}")
            return "Error al completar el onboarding. Por favor, intenta nuevamente."
    
    async def _handle_unknown_state(self, tenant_id: str, phone: str, message: str, onboarding_data: Dict) -> str:
        """Handle unknown onboarding state"""
        logger.warning(f"Unknown onboarding state for tenant {tenant_id}: {onboarding_data.get('current_state')}")
        
        # Reset to start
        await self._update_onboarding_state(tenant_id, phone, OnboardingState.START)
        
        return """⚠️ *Estado desconocido.*

He reiniciado el proceso de onboarding. Vamos a empezar de nuevo.

Escribe "configurar" para comenzar."""
    
    # ============================================
    # HELPER METHODS
    # ============================================
    
    def _format_business_hours(self, hours: Dict[str, Any]) -> str:
        """Format business hours for display"""
        days_map = {
            "monday": "Lunes",
            "tuesday": "Martes",
            "wednesday": "Miércoles",
            "thursday": "Jueves",
            "friday": "Viernes",
            "saturday": "Sábado",
            "sunday": "Domingo"
        }

        lines = []
        for day, times in hours.items():
            day_name = days_map.get(day, day)
            if times.get("closed"):
                lines.append(f"• {day_name}: cerrado")
            else:
                lines.append(f"• {day_name}: {times['open']} - {times['close']}")

        return "\n".join(lines)
    
    def _parse_product_info(self, message: str) -> Dict[str, Any]:
        """Parse product information from user message"""
        product = {
            "name": "",
            "price": 0,
            "description": "",
            "category": ""
        }
        
        lines = message.strip().split("\n")
        
        for line in lines:
            line_lower = line.lower().strip()
            
            if line_lower.startswith("nombre:"):
                product["name"] = line[7:].strip()
            elif line_lower.startswith("precio:"):
                try:
                    price_str = line[7:].strip().replace("$", "").replace(",", "")
                    product["price"] = float(price_str)
                except ValueError:
                    pass
            elif line_lower.startswith("descripción:") or line_lower.startswith("descripcion:"):
                product["description"] = line[12:].strip()
            elif line_lower.startswith("categoría:") or line_lower.startswith("categoria:"):
                product["category"] = line[10:].strip()
        
        # If no structured format, try to extract from natural language
        if not product["name"]:
            # Try to find price in message
            price_match = re.search(r'\$?\s*(\d+\.?\d*)', message)
            if price_match:
                product["price"] = float(price_match.group(1))
            
            # Try to find product name (first line or longest line)
            lines = [l.strip() for l in message.split("\n") if l.strip()]
            if lines:
                # Filter out lines that look like prices or descriptions
                name_lines = [l for l in lines if not re.match(r'^[\$€£]?\s*\d+\.?\d*', l)]
                if name_lines:
                    product["name"] = name_lines[0]
        
        return product
    
    async def _save_product(self, tenant_id: str, phone: str, product_info: Dict[str, Any], photo_url: Optional[str] = None) -> bool:
        """Save product to database"""
        try:
            # Get category ID or create default
            category_result = self.db.table("categories").select("id").eq(
                "tenant_id", tenant_id
            ).eq("name", product_info.get("category", "Sin categoría")).limit(1).execute()
            
            category_id = None
            if category_result.data:
                category_id = category_result.data[0]["id"]
            else:
                # Create default category
                category_result = self.db.table("categories").insert({
                    "tenant_id": tenant_id,
                    "name": product_info.get("category", "Sin categoría"),
                    "sort_order": 99,
                    "is_active": True
                }).execute()
                if category_result.data:
                    category_id = category_result.data[0]["id"]
            
            # Create product
            product_data = {
                "tenant_id": tenant_id,
                "name": product_info["name"],
                "price": product_info["price"],
                "description": product_info.get("description", ""),
                "category_id": category_id,
                "is_active": True,
                "track_stock": False
            }
            
            if photo_url:
                product_data["image_url"] = photo_url
            
            result = self.db.table("items").insert(product_data).execute()
            
            if result.data:
                logger.info(f"Product saved: {product_info['name']} for tenant {tenant_id}")
                return True
            
            return False
        
        except Exception as e:
            logger.error(f"Error saving product: {e}")
            return False
    
    async def _get_onboarding_session(self, tenant_id: str, phone: str) -> Dict[str, Any]:
        """Get or create onboarding session"""
        session_key = f"{tenant_id}:{phone}"
        
        if session_key not in self._onboarding_sessions:
            self._onboarding_sessions[session_key] = {
                "current_state": OnboardingState.START,
                "created_at": datetime.now().isoformat()
            }
        
        return self._onboarding_sessions[session_key]
    
    async def _update_onboarding_state(self, tenant_id: str, phone: str, state: str) -> None:
        """Update onboarding state"""
        session_key = f"{tenant_id}:{phone}"
        
        if session_key in self._onboarding_sessions:
            self._onboarding_sessions[session_key]["current_state"] = state
            self._onboarding_sessions[session_key]["updated_at"] = datetime.now().isoformat()
        
        # Also update session in database
        try:
            session_result = self.db.table("conversation_sessions").select("id").eq(
                "tenant_id", tenant_id
            ).eq("customer_phone", phone).limit(1).execute()
            
            if session_result.data:
                session_id = session_result.data[0]["id"]
                self.db.table("conversation_sessions").update({
                    "current_state": state,
                    "updated_at": datetime.now().isoformat()
                }).eq("id", session_id).execute()
        except Exception as e:
            logger.error(f"Error updating session state: {e}")
    
    async def _update_onboarding_data(self, tenant_id: str, phone: str, data: Dict[str, Any]) -> None:
        """Update onboarding session data"""
        session_key = f"{tenant_id}:{phone}"
        
        if session_key in self._onboarding_sessions:
            self._onboarding_sessions[session_key].update(data)
            self._onboarding_sessions[session_key]["updated_at"] = datetime.now().isoformat()
        
        # Update session data in database
        try:
            session_result = self.db.table("conversation_sessions").select("id, session_data").eq(
                "tenant_id", tenant_id
            ).eq("customer_phone", phone).limit(1).execute()
            
            if session_result.data:
                session_id = session_result.data[0]["id"]
                current_data = session_result.data[0].get("session_data", {}) or {}
                current_data.update(data)
                
                self.db.table("conversation_sessions").update({
                    "session_data": current_data,
                    "updated_at": datetime.now().isoformat()
                }).eq("id", session_id).execute()
        except Exception as e:
            logger.error(f"Error updating session data: {e}")


# Global instance
onboarding_handler = OnboardingHandler(None)
