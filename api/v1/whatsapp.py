"""
WhatsApp API usando Meta (Facebook) WhatsApp Business API
Documentación: https://developers.facebook.com/docs/whatsapp/cloud-api
"""
import os
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import httpx
import json
from datetime import datetime
import logging
import asyncio
from dataclasses import dataclass, field

from api.deps import get_current_tenant
from db.whatsapp_config import (
    delete_config,
    fetch_config,
    find_tenant_id_by_phone_number_id,
    save_config,
)
from middleware.rate_limiter import limiter
from services.whatsapp.meta_service import MetaWhatsAppService
from db.token_crypto import TokenEncryptionUnavailable
from utils.log_privacy import preview, tel

router = APIRouter()
logger = logging.getLogger(__name__)

# Simple in-memory cache for processed message IDs (prevents duplicate webhook processing)
_processed_message_ids = set()

# Message buffer for multi-message context (accumulates messages within time window)
@dataclass
class MessageBuffer:
    messages: List[str] = field(default_factory=list)
    message_ids: List[str] = field(default_factory=list)
    timer: Optional[asyncio.Task] = None
    last_updated: datetime = field(default_factory=datetime.utcnow)

_message_buffers: Dict[str, MessageBuffer] = {}  # key: "{tenant_id}:{phone}" -> MessageBuffer
# Cuanto se espera por si el cliente sigue escribiendo.
#
# Eran 10 segundos fijos para todo mensaje, y se notaban: en la primera
# conversacion real cada respuesta llegaba un minuto despues de la anterior. El
# buffer existe para juntar a quien parte una idea en trozos -- "quiero" /
# "una hamburguesa" / "con queso" -- no para castigar a quien escribe de una vez.
ESPERA_ENTRE_FRAGMENTOS = 2.0
BUFFER_MAX_SIZE = 10  # Maximum messages to accumulate

# Un mensaje asi de largo ya es una idea completa; esperar mas no junta nada.
LARGO_MENSAJE_COMPLETO = 25
_FINALES_DE_FRASE = (".", "!", "?", "…", "‽")


def espera_para(texto: str) -> float:
    """
    Segundos que conviene esperar tras este mensaje antes de contestar.

    Cero cuando se ve terminado -- termina en signo de puntuacion, o es
    suficientemente largo --, porque ahi la espera no agrupa nada y solo retrasa
    la respuesta. Dos segundos cuando es un fragmento corto y suelto, que es
    justo el caso para el que se invento el buffer.

    Funcion pura para poder probar el criterio sin relojes ni tareas.
    """
    limpio = (texto or "").strip()
    if not limpio:
        return ESPERA_ENTRE_FRAGMENTOS
    if limpio.endswith(_FINALES_DE_FRASE):
        return 0.0
    if len(limpio) >= LARGO_MENSAJE_COMPLETO:
        return 0.0
    return ESPERA_ENTRE_FRAGMENTOS


def combine_messages(messages: List[str]) -> str:
    """Pure function: joins a list of messages into a single string separated by spaces.

    This is the canonical way to combine buffered messages before processing.
    Buffer key format: "{tenant_id}:{phone}" (see process_meta_message).
    """
    return " ".join(messages)

def mask_token(token: str) -> str:
    """Enmascara un access token mostrando solo los primeros 10 y últimos 4 caracteres."""
    if len(token) > 14:
        return token[:10] + "..." + token[-4:]
    return "***"


def is_processed(message_id: str, cache: set) -> bool:
    """Pure function: returns True if message_id is in cache, otherwise adds it and returns False."""
    if message_id in cache:
        return True
    cache.add(message_id)
    return False


def _is_message_processed(message_id: str) -> bool:
    """Check if a message has already been processed (uses global cache with size limit)."""
    if len(_processed_message_ids) > 1000:
        _processed_message_ids.clear()
    return is_processed(message_id, _processed_message_ids)

class MetaWhatsAppConfig(BaseModel):
    phone_number_id: str
    access_token: str
    business_account_id: Optional[str] = None
    phone_number: Optional[str] = None

class WhatsAppMessageRequest(BaseModel):
    to: str
    message: str


@router.get("/health")
async def get_whatsapp_health(tenant: dict = Depends(get_current_tenant)):
    """Verificar estado de la conexión con Meta API para el tenant autenticado"""
    from db.supabase import get_supabase_client
    
    db = get_supabase_client()
    
    # Obtener config del tenant
    config = fetch_config(db, tenant["id"])

    if not config:
        return {
            "configured": False,
            "message": "WhatsApp no configurado. Ve a Configuración > WhatsApp."
        }

    # Verificar credenciales
    service = MetaWhatsAppService(
        phone_number_id=config.get("phone_number_id"),
        access_token=config.get("access_token")
    )
    
    health = service.health_check()
    
    return {
        "configured": True,
        "connected": health.get("connected", False),
        "phone_number_id": config.get("phone_number_id"),
        "timestamp": datetime.now().isoformat()
    }

@router.get("/health/public")
async def get_whatsapp_health_public():
    """Verificar estado básico del servicio WhatsApp (público)"""
    return {
        "service": "whatsapp",
        "status": "available",
        "message": "WhatsApp API está funcionando. Usa el dashboard para configurar.",
        "timestamp": datetime.now().isoformat()
    }

@router.get("/config")
async def get_whatsapp_config(tenant: dict = Depends(get_current_tenant)):
    """Obtener configuración de WhatsApp del tenant (sin exponer token completo)"""
    from db.supabase import get_supabase_client
    
    db = get_supabase_client()
    config = fetch_config(db, tenant["id"])

    if not config:
        return {"configured": False}

    # Mask token for security
    token = config.get("access_token", "")
    masked_token = mask_token(token)
    
    return {
        "configured": True,
        "config": {
            "phone_number_id": config.get("phone_number_id"),
            "phone_number": config.get("phone_number"),
            "business_account_id": config.get("business_account_id"),
            "access_token_masked": masked_token,
            "is_connected": config.get("is_connected", False)
        }
    }

@router.post("/config")
async def save_whatsapp_config(
    data: MetaWhatsAppConfig,
    tenant: dict = Depends(get_current_tenant)
):
    """Guardar configuración de Meta WhatsApp API"""
    try:
        from db.supabase import get_supabase_client
        
        db = get_supabase_client()
        
        logger.info(f"Saving WhatsApp config for tenant {tenant['id']}")
        logger.info(
            "Phone ID: %s, Business ID: %s, Phone: %s",
            data.phone_number_id, data.business_account_id, tel(data.phone_number),
        )
        
        # Verificar credenciales contra Meta Graph API
        service = MetaWhatsAppService(
            phone_number_id=data.phone_number_id,
            access_token=data.access_token
        )
        
        network_error: Optional[str] = None
        is_valid = False

        try:
            verification = service.verify_credentials()
            is_valid = verification.get("valid", False)
            error_detail = verification.get("error", "")
            logger.info(f"Credential verification result: valid={is_valid}")
        except Exception as e:
            # Error de red / timeout — no podemos confirmar si las credenciales son válidas
            logger.error(f"Network error during credential verification: {e}")
            network_error = str(e)
            error_detail = network_error

        # Si las credenciales son explícitamente inválidas (token expirado / incorrecto),
        # rechazar sin guardar (Requirement 2.3)
        if not is_valid and network_error is None:
            raise HTTPException(
                status_code=400,
                detail=f"Credenciales inválidas: el token de acceso es incorrecto o ha expirado. {error_detail}".strip()
            )

        # Preparar datos — solo guardamos cuando is_valid=True o hubo error de red
        config_data = {
            "tenant_id": tenant["id"],
            "phone_number_id": data.phone_number_id,
            "access_token": data.access_token,
            "is_connected": is_valid,
            "provider": "meta",
            "updated_at": datetime.now().isoformat()
        }
        
        # Solo agregar campos opcionales si tienen valor
        if data.business_account_id:
            config_data["business_account_id"] = data.business_account_id
        if data.phone_number:
            config_data["phone_number"] = data.phone_number
        
        logger.info(f"Config data prepared: {config_data.keys()}")

        # save_config cifra el access_token antes de escribirlo. Si no hay clave
        # configurada lanza TokenEncryptionUnavailable y no guarda nada: preferimos
        # fallar a guardar la credencial en claro creyendo que la ciframos.
        try:
            save_config(db, tenant["id"], config_data)
        except TokenEncryptionUnavailable:
            logger.error("WHATSAPP_TOKEN_ENCRYPTION_KEY no configurada; no se guarda el token")
            raise HTTPException(
                status_code=500,
                detail="El servidor no puede almacenar credenciales de forma segura. Avisa al administrador.",
            )
        except Exception as e:
            logger.error(f"Database error: {e}")
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
        
        if is_valid:
            return {
                "status": "success",
                "message": "WhatsApp configurado y verificado correctamente",
                "verified": True,
                "is_connected": True,
                "warning": None
            }
        else:
            # network_error path: guardado con is_connected=False
            return {
                "status": "success",
                "message": "Configuración guardada. No se pudo verificar la conexión con Meta por un error de red.",
                "verified": False,
                "is_connected": False,
                "warning": error_detail
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in save_whatsapp_config: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

@router.get("/webhook")
async def verify_webhook(request: Request):
    """Verificar webhook con Meta WhatsApp API"""
    from config import get_settings
    
    import hmac

    settings = get_settings()
    mode = request.query_params.get('hub.mode')
    token = request.query_params.get('hub.verify_token')
    challenge = request.query_params.get('hub.challenge')

    if not settings.META_WEBHOOK_VERIFY_TOKEN:
        logger.error(
            "META_WEBHOOK_VERIFY_TOKEN no esta configurado: no se puede "
            "verificar la suscripcion del webhook. Generar uno aleatorio y "
            "cargarlo en Render y en Meta -> WhatsApp -> Configuration."
        )
        raise HTTPException(status_code=403)

    if mode == 'subscribe' and token and hmac.compare_digest(
        token, settings.META_WEBHOOK_VERIFY_TOKEN
    ):
        if challenge is None or not challenge.isdigit():
            logger.warning("Webhook verification sin hub.challenge valido")
            raise HTTPException(status_code=400)
        logger.info("Webhook verified successfully")
        return int(challenge)

    logger.warning("Webhook verification failed")
    raise HTTPException(status_code=403)

@router.post("/webhook")
@limiter.limit("300/minute")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Recibir mensajes y eventos de Meta WhatsApp API.

    300/minuto por IP. El trafico legitimo llega todo desde las IPs de Meta y
    ni se acerca a ese numero al volumen actual, asi que el limite solo muerde
    a una inundacion desde un origen unico. Aunque la firma ya rechaza los
    payloads falsos, cada intento sigue costando un HMAC, un log y un ciclo de
    la instancia - y la instancia sirve ~1 peticion por segundo.
    """
    from config import get_settings
    from services.whatsapp.webhook_security import (
        SIGNATURE_HEADER,
        is_valid_signature,
    )

    settings = get_settings()

    # El cuerpo crudo, no el JSON ya parseado: la firma se calcula sobre los
    # bytes exactos que mando Meta, y volver a serializar el dict cambiaria el
    # espaciado y no coincidiria.
    raw_body = await request.body()

    if settings.DEBUG:
        # En local no hay forma de firmar: el curl de la guia de testing y los
        # payloads de ejemplo no llevan App Secret. Solo aplica con DEBUG=True,
        # que en produccion es False.
        logger.warning(
            "DEBUG=True: se omite la verificacion de firma del webhook"
        )
    elif not is_valid_signature(
        settings.META_APP_SECRET,
        raw_body,
        request.headers.get(SIGNATURE_HEADER),
    ):
        if not settings.META_APP_SECRET:
            logger.error(
                "META_APP_SECRET no esta configurado: el webhook rechaza todo. "
                "Cargarlo en Render (Meta for Developers -> app -> "
                "Configuracion -> Basica -> Clave secreta)."
            )
        else:
            logger.warning(
                "Webhook rechazado: %s ausente o invalida", SIGNATURE_HEADER
            )
        # Fuera del try de abajo a proposito: ese except devuelve 200 con
        # {"status": "error"}, que convertiria este rechazo en una aceptacion.
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        data = json.loads(raw_body)
        logger.info(f"=== WEBHOOK POST RECEIVED ===")
        # El payload entero eran 1000 caracteres con el telefono y el texto del
        # cliente en cada linea de log. Lo que servia para depurar era la forma,
        # y esa se registra unas lineas mas abajo: entries, changes y messages.

        # Procesar entries
        entries_count = len(data.get("entry", []))
        logger.info(f"Entries count: {entries_count}")
        
        for entry in data.get("entry", []):
            changes_count = len(entry.get("changes", []))
            logger.info(f"Changes count: {changes_count}")
            
            for change in entry.get("changes", []):
                value = change.get("value", {})
                
                # Mensajes entrantes
                if "messages" in value:
                    messages_count = len(value.get("messages", []))
                    logger.info(f"Messages count: {messages_count}")
                    
                    for message in value.get("messages", []):
                        phone = message.get("from")
                        text = message.get("text", {}).get("body", "")
                        message_id = message.get("id")  # Unique message ID from Meta
                        
                        logger.info(
                            "Message details - ID: %s, From: %s, Body: %s",
                            message_id, tel(phone), preview(text),
                        )
                        
                        # DEDUPLICATION: Skip if we've already processed this message
                        if message_id and _is_message_processed(message_id):
                            logger.info(f"Skipping duplicate message: {message_id}")
                            continue
                        
                        # Buscar tenant por número de teléfono
                        from db.supabase import get_supabase_client
                        db = get_supabase_client()
                        
                        # El phone_number_id viene en los metadata
                        metadata = value.get("metadata", {})
                        phone_number_id = metadata.get("phone_number_id")
                        
                        logger.info(f"Looking for tenant with phone_number_id: {phone_number_id}")
                        
                        tenant_id = find_tenant_id_by_phone_number_id(db, phone_number_id)

                        if tenant_id:
                            logger.info("✓ Message from %s to tenant %s: %s", tel(phone), tenant_id, preview(text))
                            
                            # Procesar mensaje (con buffering para múltiples mensajes)
                            background_tasks.add_task(
                                process_meta_message,
                                tenant_id,
                                phone,
                                text,
                                phone_number_id,
                                message_id
                            )
                            logger.info(f"✓ Background task added for processing with message_id: {message_id}")
                        else:
                            logger.error(f"✗ No tenant found for phone_number_id: {phone_number_id}")
                            logger.error(f"Check your whatsapp_configs table has this phone_number_id: {phone_number_id}")
                
                # Estados de mensajes
                if "statuses" in value:
                    for status in value.get("statuses", []):
                        logger.info(f"Message status: {status.get('id')} - {status.get('status')}")
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "error", "message": str(e)}

async def _process_buffered_messages(tenant_id: str, phone: str, phone_id: str):
    """Process accumulated messages from buffer"""
    global _message_buffers
    
    try:
        # Get and clear buffer for this phone
        buffer_key = f"{tenant_id}:{phone}"  # Canonical key format: "{tenant_id}:{phone}"
        if buffer_key not in _message_buffers:
            return
        
        buffer = _message_buffers[buffer_key]
        messages = buffer.messages.copy()
        message_ids = buffer.message_ids.copy()
        
        # Clear buffer
        del _message_buffers[buffer_key]
        
        if not messages:
            return
        
        # Join all messages with spaces using the canonical combine_messages function
        combined_text = combine_messages(messages)
        
        logger.info("=" * 60)
        logger.info("🔄 PROCESSING BUFFERED MESSAGES for %s", tel(phone))
        logger.info(f"   Total messages: {len(messages)}")
        logger.info(f"   Message IDs: {message_ids}")
        logger.info("   Combined text: %s", preview(combined_text))
        logger.info("=" * 60)
        
        from services.whatsapp.meta_bot_service import bot_service
        from db.supabase import get_supabase_client
        
        # Obtener token del tenant
        db = get_supabase_client()
        config = fetch_config(db, tenant_id, "access_token")

        if not config:
            logger.error(f"No config found for tenant {tenant_id}")
            return

        token = config["access_token"]

        # Crear instancia del servicio para responder
        service = MetaWhatsAppService(phone_number_id=phone_id, access_token=token)
        
        # Procesar mensaje combinado con el nuevo bot service
        logger.info(f"Calling bot_service.process_message with combined text...")
        response = await bot_service.process_message(tenant_id, phone, combined_text, phone_id)
        
        # Enviar respuesta
        if response:
            logger.info("Sending response to %s", tel(phone))
            service.send_message(phone, response)
        else:
            logger.warning("No response generated for combined message: %s", preview(combined_text))
            
    except Exception as e:
        logger.error(f"ERROR in _process_buffered_messages: {e}")
        import traceback
        logger.error(traceback.format_exc())


async def process_meta_message(tenant_id: str, phone: str, text: str, phone_id: str, message_id: str = None):
    """
    Procesar mensaje entrante usando el nuevo bot service.
    Implementa buffering para acumular múltiples mensajes en un solo contexto.
    """
    global _message_buffers
    
    try:
        logger.info("📩 NEW MESSAGE from %s: %s", tel(phone), preview(text))
        
        buffer_key = f"{tenant_id}:{phone}"  # Canonical key format: "{tenant_id}:{phone}"
        
        # Check if we have an existing buffer for this user
        if buffer_key in _message_buffers:
            buffer = _message_buffers[buffer_key]
            
            # Cancel existing timer
            if buffer.timer and not buffer.timer.done():
                buffer.timer.cancel()
                logger.info("⏹️ Cancelled existing timer for %s", tel(phone))
            
            # Add message to buffer
            buffer.messages.append(text)
            if message_id:
                buffer.message_ids.append(message_id)
            buffer.last_updated = datetime.utcnow()
            
            logger.info(f"📥 Added to buffer. Total messages: {len(buffer.messages)}")
            
            # Check if buffer is full
            if len(buffer.messages) >= BUFFER_MAX_SIZE:
                logger.info(f"📦 Buffer full ({BUFFER_MAX_SIZE} messages), processing immediately...")
                await _process_buffered_messages(tenant_id, phone, phone_id)
                return
        else:
            # Create new buffer
            _message_buffers[buffer_key] = MessageBuffer(
                messages=[text],
                message_ids=[message_id] if message_id else [],
                last_updated=datetime.utcnow()
            )
            logger.info("🆕 Created new buffer for %s", tel(phone))
        
        espera = espera_para(text)

        if espera <= 0:
            # El mensaje se ve terminado: esperar no agruparia nada y el cliente
            # se queda mirando la pantalla.
            logger.info("▶️ Mensaje completo, se procesa ya para %s", tel(phone))
            await _process_buffered_messages(tenant_id, phone, phone_id)
            return

        async def delayed_process():
            await asyncio.sleep(espera)
            logger.info("⏰ Timer expired for %s, processing buffered messages...", tel(phone))
            await _process_buffered_messages(tenant_id, phone, phone_id)

        # Store the timer task
        _message_buffers[buffer_key].timer = asyncio.create_task(delayed_process())

        logger.info("⏳ Esperando %.1fs por si llega otro fragmento...", espera)
            
    except Exception as e:
        logger.error(f"ERROR in process_meta_message: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        # Fallback: process immediately on error
        try:
            from services.whatsapp.meta_bot_service import bot_service
            from db.supabase import get_supabase_client
            
            db = get_supabase_client()
            config = fetch_config(db, tenant_id, "access_token")

            if config:
                token = config["access_token"]
                service = MetaWhatsAppService(phone_number_id=phone_id, access_token=token)
                response = await bot_service.process_message(tenant_id, phone, text, phone_id)
                
                if response:
                    service.send_message(phone, response)
        except Exception as fallback_error:
            logger.error(f"Fallback processing also failed: {fallback_error}")

@router.post("/send-message")
async def send_whatsapp_message(
    message: WhatsAppMessageRequest,
    tenant: dict = Depends(get_current_tenant)
):
    """Enviar mensaje de WhatsApp usando Meta API"""
    from db.supabase import get_supabase_client
    
    db = get_supabase_client()
    
    # Obtener config
    config = fetch_config(db, tenant["id"])

    if not config:
        raise HTTPException(status_code=404, detail="WhatsApp no configurado")

    # Crear servicio y enviar
    service = MetaWhatsAppService(
        phone_number_id=config["phone_number_id"],
        access_token=config["access_token"]
    )
    
    result = service.send_message(message.to, message.message)
    
    if result.get("status") == "failed":
        raise HTTPException(status_code=400, detail=result.get("error"))
    
    return result

@router.get("/templates")
async def get_message_templates(tenant: dict = Depends(get_current_tenant)):
    """Obtener plantillas de mensajes aprobadas por Meta"""
    from db.supabase import get_supabase_client
    
    db = get_supabase_client()
    config = fetch_config(db, tenant["id"])

    if not config:
        raise HTTPException(status_code=404, detail="WhatsApp no configurado")

    service = MetaWhatsAppService(
        phone_number_id=config["phone_number_id"],
        access_token=config["access_token"]
    )
    
    templates = service.get_templates()
    return templates

@router.get("/storefront-link")
async def get_storefront_link(
    cart_id: str,
    tenant: dict = Depends(get_current_tenant)
):
    """
    Genera un enlace wa.me para que el cliente finalice su compra por WhatsApp.

    El enlace pre-rellena un mensaje con el cart_id y los nombres de los productos.
    Requiere que el tenant tenga `whatsapp_number` en la tabla `tenants` y el
    carrito activo en Redis.
    """
    import json as _json
    from utils.whatsapp_link import generate_whatsapp_link

    # 1. Obtener whatsapp_number del tenant
    whatsapp_number = tenant.get("whatsapp_number")
    if not whatsapp_number:
        raise HTTPException(
            status_code=400,
            detail="El tenant no tiene un número de WhatsApp configurado en su perfil."
        )

    # 2. Obtener carrito de Redis
    try:
        from db.redis import get_redis_client as _get_redis
        import json as _json
        redis_client = _get_redis()
        cart_data = await redis_client.get(f"cart:{cart_id}")
    except Exception as e:
        logger.error(f"Error conectando a Redis: {e}")
        raise HTTPException(status_code=503, detail="No se pudo acceder al carrito. Intenta de nuevo.")

    if not cart_data:
        raise HTTPException(status_code=404, detail="Carrito no encontrado o expirado.")

    cart = _json.loads(cart_data)
    products = cart.get("items", [])

    if not products:
        raise HTTPException(status_code=400, detail="El carrito está vacío.")

    # 3. Generar enlace
    link = generate_whatsapp_link(whatsapp_number, cart_id, products)

    return {"link": link, "cart_id": cart_id}


@router.delete("/config")
async def delete_whatsapp_config(tenant: dict = Depends(get_current_tenant)):
    """Eliminar configuración de WhatsApp"""
    from db.supabase import get_supabase_client
    
    db = get_supabase_client()
    delete_config(db, tenant["id"])
    
    return {"status": "deleted", "message": "Configuración eliminada"}
