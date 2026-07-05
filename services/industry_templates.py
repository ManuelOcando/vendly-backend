"""
Industry Templates Service

Provides default templates for different business industries including
restaurant, retail, and professional services configurations.
"""
from typing import Dict, Any, List
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class IndustryType(str, Enum):
    """Supported business industries"""
    RESTAURANT = "restaurant"
    RETAIL = "retail"
    SERVICES = "services"


class IndustryTemplatesService:
    """
    Service for managing industry-specific templates including:
    - Default product categories
    - Workflow templates
    - Message templates
    """
    
    def __init__(self):
        self._templates = self._load_industry_templates()
    
    def _load_industry_templates(self) -> Dict[str, Any]:
        """Load default industry templates"""
        return {
            IndustryType.RESTAURANT: {
                "name": "Restaurant Template",
                "industry": IndustryType.RESTAURANT,
                "description": "Configuración predefinida para restaurantes y servicios de alimentación",
                "configuration": {
                    "default_categories": [
                        {"name": "Entradas", "order": 1, "icon": "🥗", "description": "Entradas y aperitivos"},
                        {"name": "Platos Principales", "order": 2, "icon": "🍽️", "description": "Platos fuertes y principales"},
                        {"name": "Postres", "order": 3, "icon": "🍰", "description": "Postres y dulces"},
                        {"name": "Bebidas", "order": 4, "icon": "🥤", "description": "Bebidas y cócteles"}
                    ],
                    "workflow_templates": [
                        {
                            "name": "order_flow",
                            "description": "Flujo estándar de pedidos para restaurantes",
                            "states": ["browse", "select", "customize", "confirm", "payment"]
                        },
                        {
                            "name": "customization_flow",
                            "description": "Flujo para personalización de platos",
                            "states": ["browse", "select", "customize", "confirm", "payment"]
                        },
                        {
                            "name": "special_requests",
                            "description": "Flujo para solicitudes especiales (cumpleaños, eventos)",
                            "states": ["greet", "inquire", "quote", "confirm", "payment"]
                        }
                    ],
                    "message_templates": {
                        "greeting": "¡Hola! 👋 Bienvenido a {store_name}. ¿Qué te gustaría ordenar hoy?",
                        "order_confirmation": "✅ ¡Pedido confirmado! Tu número es {order_number}.",
                        "delivery_estimate": "⏰ Tiempo estimado de entrega: {time} minutos.",
                        "payment_instructions": "Por favor, contacta al vendedor para recibir las instrucciones de pago.",
                        "out_of_stock": "Lo siento, {product_name} no está disponible en este momento.",
                        "customization_options": "¿Te gustaría personalizar tu pedido? Puedes elegir:\n• Ingredientes adicionales\n• Eliminar ingredientes\n• Cambios especiales"
                    }
                },
                "default_messages": {
                    "welcome": "¡Bienvenido a {store_name}! 🍽️\n\n¿Qué te gustaría ordenar hoy?\n\nEscribe 'menu' para ver nuestros productos.",
                    "hours": "🕒 Nuestros horarios son:\n• Lunes a Viernes: 11:00 AM - 10:00 PM\n• Sábado: 11:00 AM - 11:00 PM\n• Domingo: 12:00 PM - 9:00 PM",
                    "delivery": "🚚 Realizamos entregas a domicilio en un radio de {distance} km.\n• Entrega gratuita en pedidos mayores a ${amount}",
                    "menu_header": "📋 *Nuestro Menú*",
                    "menu_item": "• {name} - ${price}\n  {description}",
                    "menu_footer": "\nPara ordenar, escribe el nombre del producto o escribe 'menu' para ver todos.",
                    "special_offers": "🌟 *Ofertas del Día* 🌟\n\n{offers}\n\nEscribe 'ver ofertas' para más detalles.",
                    "contact_info": "📞 Contáctanos:\n{phone}\n📍 {address}\n📧 {email}"
                },
                "default_categories_sql": [
                    {"name": "Entradas", "order": 1, "icon": "🥗", "description": "Entradas y aperitivos"},
                    {"name": "Platos Principales", "order": 2, "icon": "🍽️", "description": "Platos fuertes y principales"},
                    {"name": "Postres", "order": 3, "icon": "🍰", "description": "Postres y dulces"},
                    {"name": "Bebidas", "order": 4, "icon": "🥤", "description": "Bebidas y cócteles"}
                ],
                "workflow_templates_config": [
                    {
                        "name": "order_flow",
                        "description": "Flujo estándar de pedidos para restaurantes",
                        "prompt_template": """Eres un asistente de restaurante llamado {bot_name}.
Tu objetivo es ayudar a los clientes a ordenar comida.

Flujo de conversación:
1. Saluda al cliente
2. Muestra el menú cuando lo pida
3. Ayuda a seleccionar productos
4. Permite personalizar pedidos
5. Confirma el pedido
6. Proporciona instrucciones de pago

Reglas:
- Sé amable y profesional
- Usa emojis apropiados
- Mantén respuestas concisas
- Ofrece recomendaciones cuando sea apropiado
- Maneja preguntas frecuentes sobre el menú""",
                        "fallback_responses": {
                            "unknown_product": "No encontré ese producto. ¿Te gustaría ver el menú completo?",
                            "out_of_stock": "Lo siento, ese producto no está disponible. ¿Te gustaría ver otra opción?",
                            "customization": "Claro, puedo ayudarte a personalizar tu pedido. ¿Qué cambios te gustaría hacer?"
                        }
                    },
                    {
                        "name": "customization_flow",
                        "description": "Flujo para personalización de platos",
                        "prompt_template": """Eres un asistente de restaurante especializado en personalización de pedidos.

Tu objetivo es ayudar a los clientes a personalizar sus platos según sus preferencias.

Flujo de conversación:
1. Pregunta qué producto le gustaría personalizar
2. Ofrece opciones de personalización
3. Confirma los cambios
4. Agrega al carrito

Opciones comunes de personalización:
- Ingredientes adicionales (+$X)
- Eliminar ingredientes
- Cambios especiales (sin gluten, sin lactosa, etc.)""",
                        "fallback_responses": {
                            "no_customization": "No hay costos adicionales para eliminar ingredientes. ¿Qué te gustaría cambiar?",
                            "extra_cost": "Ese cambio tiene un costo adicional de ${cost}. ¿Deseas proceder?",
                            "confirm_changes": "✅ Pedido personalizado confirmado. ¿Deseas agregar algo más?"
                        }
                    }
                ]
            },
            IndustryType.RETAIL: {
                "name": "Retail Template",
                "industry": IndustryType.RETAIL,
                "description": "Configuración predefinida para tiendas retail y comercio",
                "configuration": {
                    "default_categories": [
                        {"name": "Ropa", "order": 1, "icon": "👕", "description": "Ropa y accesorios"},
                        {"name": "Calzado", "order": 2, "icon": "👟", "description": "Calzado y zapatillas"},
                        {"name": "Accesorios", "order": 3, "icon": "👜", "description": "Bolsos, joyas y accesorios"},
                        {"name": "Promociones", "order": 4, "icon": "🔥", "description": "Ofertas y descuentos"}
                    ],
                    "workflow_templates": [
                        {
                            "name": "product_inquiry",
                            "description": "Flujo para consultas sobre productos",
                            "states": ["greet", "inquire", "details", "purchase", "payment"]
                        },
                        {
                            "name": "size_guide",
                            "description": "Flujo para guía de tallas",
                            "states": ["greet", "inquire", "guide", "purchase", "payment"]
                        },
                        {
                            "name": "shipping_info",
                            "description": "Flujo para información de envío",
                            "states": ["greet", "inquire", "shipping", "purchase", "payment"]
                        },
                        {
                            "name": "return_policy",
                            "description": "Flujo para políticas de devolución",
                            "states": ["greet", "inquire", "policy", "return", "refund"]
                        }
                    ],
                    "message_templates": {
                        "greeting": "¡Hola! 👋 Bienvenido a {store_name}. ¿En qué puedo ayudarte?",
                        "order_confirmation": "✅ ¡Orden confirmada! Número: {order_number}",
                        "shipping": "📦 Tu orden será enviada en {days} días hábiles.",
                        "size_guide": "📏 *Guía de Tallas*:\n{sizes}",
                        "return_policy": "🔄 *Política de Devoluciones*:\n{policy}"
                    }
                },
                "default_messages": {
                    "welcome": "¡Bienvenido a {store_name}! 🛍️\n\n¿Qué te gustaría comprar hoy?\n\nEscribe 'menu' para ver nuestros productos.",
                    "shipping": "🚚 Envíos a todo el país:\n• Standard: 3-5 días hábiles\n• Express: 1-2 días hábiles\n• Retiro en tienda: Disponible",
                    "returns": "🔄 Política de devoluciones:\n• 30 días para devolución\n• Productos sin usar\n• Con etiqueta original",
                    "size_guide": "📏 *Guía de Tallas*:\n• Talla S: 34-36\n• Talla M: 38-40\n• Talla L: 42-44\n• Talla XL: 46-48",
                    "contact_info": "📞 Contáctanos:\n{phone}\n📍 {address}\n📧 {email}"
                },
                "default_categories_sql": [
                    {"name": "Ropa", "order": 1, "icon": "👕", "description": "Ropa y accesorios"},
                    {"name": "Calzado", "order": 2, "icon": "👟", "description": "Calzado y zapatillas"},
                    {"name": "Accesorios", "order": 3, "icon": "👜", "description": "Bolsos, joyas y accesorios"},
                    {"name": "Promociones", "order": 4, "icon": "🔥", "description": "Ofertas y descuentos"}
                ],
                "workflow_templates_config": [
                    {
                        "name": "product_inquiry",
                        "description": "Flujo para consultas sobre productos",
                        "prompt_template": """Eres un asistente de tienda retail llamado {bot_name}.
Tu objetivo es ayudar a los clientes a encontrar productos y completar compras.

Flujo de conversación:
1. Saluda al cliente
2. Pregunta qué producto busca
3. Muestra detalles del producto
4. Ayuda con selección de talla/color
5. Procede a compra
6. Proporciona información de envío

Reglas:
- Sé amable y profesional
- Usa emojis apropiados
- Ofrece recomendaciones de productos similares
- Maneja preguntas sobre tallas y materiales""",
                        "fallback_responses": {
                            "unknown_product": "No encontré ese producto. ¿Te gustaría ver nuestro catálogo?",
                            "size_question": "¿Qué talla necesitas? Te puedo ayudar a encontrar la correcta.",
                            "material_question": "Ese producto está hecho de {material}. ¿Te gustaría ver más detalles?"
                        }
                    }
                ]
            },
            IndustryType.SERVICES: {
                "name": "Services Template",
                "industry": IndustryType.SERVICES,
                "description": "Configuración predefinida para servicios profesionales",
                "configuration": {
                    "default_categories": [
                        {"name": "Servicios Básicos", "order": 1, "icon": "🔧", "description": "Servicios estándar"},
                        {"name": "Servicios Premium", "order": 2, "icon": "💎", "description": "Servicios de lujo"},
                        {"name": "Consultorías", "order": 3, "icon": "💼", "description": "Servicios de consultoría"}
                    ],
                    "workflow_templates": [
                        {
                            "name": "appointment_booking",
                            "description": "Flujo para reservar citas",
                            "states": ["greet", "inquire", "availability", "schedule", "confirm"]
                        },
                        {
                            "name": "service_inquiry",
                            "description": "Flujo para consultas sobre servicios",
                            "states": ["greet", "inquire", "details", "quote", "book"]
                        },
                        {
                            "name": "quote_request",
                            "description": "Flujo para solicitar presupuestos",
                            "states": ["greet", "inquire", "details", "quote", "confirm"]
                        },
                        {
                            "name": "follow_up",
                            "description": "Flujo para seguimiento post-servicio",
                            "states": ["greet", "check", "feedback", "review"]
                        }
                    ],
                    "message_templates": {
                        "greeting": "¡Hola! 👋 Bienvenido a {store_name}. ¿Cómo podemos ayudarte?",
                        "appointment_confirmed": "✅ ¡Cita confirmada! {date} a las {time}",
                        "availability": "📅 Disponibilidad actual:\n{days}",
                        "quote": "💰 *Presupuesto*:\n{quote_details}\n\nTotal: ${amount}",
                        "follow_up": "👋 Hola {name}, ¿cómo fue tu experiencia con {service}?"
                    }
                },
                "default_messages": {
                    "welcome": "¡Bienvenido a {store_name}! 🛠️\n\n¿Qué servicio te gustaría solicitar hoy?\n\nEscribe 'agendar' para reservar una cita.",
                    "appointments": "📅 Agenda tus citas con nosotros:\n• Lunes a Viernes: 9:00 AM - 8:00 PM\n• Sábado: 10:00 AM - 6:00 PM\n\nEscribe 'agendar' para reservar.",
                    "services": "🔧 Nuestros servicios:\n• Servicio Básico: ${price_basic}\n• Servicio Premium: ${price_premium}\n• Consultoría: ${price_consultation}",
                    "availability": "📅 *Disponibilidad*:\n• Lunes: 9:00 AM - 8:00 PM\n• Martes: 9:00 AM - 8:00 PM\n• Miércoles: 9:00 AM - 8:00 PM\n• Jueves: 9:00 AM - 8:00 PM\n• Viernes: 9:00 AM - 8:00 PM\n• Sábado: 10:00 AM - 6:00 PM",
                    "contact_info": "📞 Contáctanos:\n{phone}\n📍 {address}\n📧 {email}"
                },
                "default_categories_sql": [
                    {"name": "Servicios Básicos", "order": 1, "icon": "🔧", "description": "Servicios estándar"},
                    {"name": "Servicios Premium", "order": 2, "icon": "💎", "description": "Servicios de lujo"},
                    {"name": "Consultorías", "order": 3, "icon": "💼", "description": "Servicios de consultoría"}
                ],
                "workflow_templates_config": [
                    {
                        "name": "appointment_booking",
                        "description": "Flujo para reservar citas",
                        "prompt_template": """Eres un asistente de agendamiento llamado {bot_name}.
Tu objetivo es ayudar a los clientes a reservar citas para servicios profesionales.

Flujo de conversación:
1. Saluda al cliente
2. Pregunta qué servicio necesita
3. Muestra disponibilidad
4. Ayuda a seleccionar fecha y hora
5. Confirma la cita
6. Proporciona información de preparación

Reglas:
- Sé amable y profesional
- Usa emojis apropiados
- Maneja reprogramaciones y cancelaciones
- Proporciona recordatorios automáticos""",
                        "fallback_responses": {
                            "no_availability": "No tenemos disponibilidad para esa fecha. ¿Te gustaría ver otras fechas?",
                            "confirm_appointment": "✅ ¡Cita confirmada! Recibirás un recordatorio 24 horas antes.",
                            "reschedule": "Claro, puedo ayudarte a reprogramar. ¿Qué nueva fecha prefieres?"
                        }
                    }
                ]
            }
        }
    
    def get_template(self, industry: str) -> Dict[str, Any]:
        """Get template for specific industry"""
        return self._templates.get(industry, self._templates[IndustryType.RESTAURANT])
    
    def get_industries(self) -> List[str]:
        """Get list of supported industries"""
        return list(self._templates.keys())
    
    def get_default_categories(self, industry: str) -> List[Dict[str, Any]]:
        """Get default categories for industry"""
        template = self.get_template(industry)
        return template.get("configuration", {}).get("default_categories", [])
    
    def get_workflow_templates(self, industry: str) -> List[Dict[str, Any]]:
        """Get workflow templates for industry"""
        template = self.get_template(industry)
        return template.get("configuration", {}).get("workflow_templates", [])
    
    def get_message_templates(self, industry: str) -> Dict[str, str]:
        """Get message templates for industry"""
        template = self.get_template(industry)
        return template.get("configuration", {}).get("message_templates", {})
    
    def get_default_messages(self, industry: str) -> Dict[str, str]:
        """Get default messages for industry"""
        template = self.get_template(industry)
        return template.get("default_messages", {})
    
    def get_workflow_templates_config(self, industry: str) -> List[Dict[str, Any]]:
        """Get detailed workflow templates configuration"""
        template = self.get_template(industry)
        return template.get("workflow_templates_config", [])
    
    def get_all_templates(self) -> Dict[str, Any]:
        """Get all industry templates"""
        return self._templates


# Global instance
industry_templates_service = IndustryTemplatesService()
