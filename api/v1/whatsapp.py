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
from services.whatsapp.meta_service import MetaWhatsAppService

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

_message_buffers: Dict[str, MessageBuffer] = {}  # phone -> MessageBuffer
BUFFER_TIMEOUT_SECONDS = 3  # Wait 3 seconds for additional messages
BUFFER_MAX_SIZE = 10  # Maximum messages to accumulate

def _is_message_processed(message_id: str) -> bool:
    """Check if a message has already been processed"""
    if message_id in _processed_message_ids:
        return True
    # Add to cache (limit size to prevent memory issues)
    if len(_processed_message_ids) > 1000:
        _processed_message_ids.clear()
    _processed_message_ids.add(message_id)
    return False

class MetaWhatsAppConfig(BaseModel):
    phone_number_id: str
    access_token: str
    business_account_id: Optional[str] = None
    phone_number: Optional[str] = None

class WhatsAppMessageRequest(BaseModel):
    to: str
    message: str

class WhatsAppConnection(BaseModel):
    store_id: str
    phone_number: str
    instance_name: str

class WhatsAppMessage(BaseModel):
    instance_id: str
    to: str
    message: str
    message_type: str = "text"

class WebhookMessage(BaseModel):
    key: Dict[str, Any]
    message: Dict[str, Any]
    instance: str
    senderData: Dict[str, Any]

@router.get("/health")
async def get_whatsapp_health(tenant: dict = Depends(get_current_tenant)):
    """Verificar estado de la conexión con Meta API para el tenant autenticado"""
    from db.supabase import get_supabase_client
    
    db = get_supabase_client()
    
    # Obtener config del tenant
    result = db.table("whatsapp_configs").select("*").eq("tenant_id", tenant["id"]).execute()
    
    if not result.data:
        return {
            "configured": False,
            "message": "WhatsApp no configurado. Ve a Configuración > WhatsApp."
        }
    
    config = result.data[0]
    
    # Verificar credenciales
    service = MetaWhatsAppService(
        phone_number_id=config.get("phone_number_id"),
        access_token=config.get("access_token")
    )
    
    health = service.health_check()
    
    return {
        "configured": True,
        "connected": health.get("connected", False),
        "status": health.get("status"),
        "app_name": health.get("name"),
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
    result = db.table("whatsapp_configs").select("*").eq("tenant_id", tenant["id"]).execute()
    
    if not result.data:
        return {"configured": False}
    
    config = result.data[0]
    
    # Mask token for security
    token = config.get("access_token", "")
    masked_token = token[:10] + "..." + token[-4:] if len(token) > 14 else "***"
    
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
        logger.info(f"Phone ID: {data.phone_number_id}, Business ID: {data.business_account_id}, Phone: {data.phone_number}")
        
        # Verificar credenciales (pero guardamos igual para debug)
        service = MetaWhatsAppService(
            phone_number_id=data.phone_number_id,
            access_token=data.access_token
        )
        
        try:
            verification = service.verify_credentials()
            is_valid = verification.get("valid", False)
            error_detail = verification.get("error", "")
            logger.info(f"Credential verification result: valid={is_valid}")
        except Exception as e:
            logger.error(f"Error during credential verification: {e}")
            is_valid = False
            error_detail = str(e)
        
        # Preparar datos
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
        
        # Verificar si ya existe
        try:
            existing = db.table("whatsapp_configs").select("id").eq("tenant_id", tenant["id"]).execute()
            logger.info(f"Existing config check: {len(existing.data) if existing.data else 0} found")
        except Exception as e:
            logger.error(f"Error checking existing config: {e}")
            existing = None
        
        # Insert o Update
        try:
            if existing and existing.data:
                result = db.table("whatsapp_configs").update(config_data).eq("tenant_id", tenant["id"]).execute()
                logger.info("Config updated successfully")
            else:
                config_data["created_at"] = datetime.now().isoformat()
                result = db.table("whatsapp_configs").insert(config_data).execute()
                logger.info("Config inserted successfully")
        except Exception as e:
            logger.error(f"Database error: {e}")
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
        
        # Mensaje según resultado
        if is_valid:
            message = "WhatsApp configurado y verificado correctamente"
        else:
            message = f"Configuración guardada pero credenciales no verificadas. Error: {error_detail}"
        
        return {
            "status": "success",
            "message": message,
            "verified": is_valid,
            "is_connected": is_valid,
            "warning": error_detail if not is_valid else None
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
    
    settings = get_settings()
    mode = request.query_params.get('hub.mode')
    token = request.query_params.get('hub.verify_token')
    challenge = request.query_params.get('hub.challenge')
    
    if mode and token:
        if mode == 'subscribe' and token == settings.META_WEBHOOK_VERIFY_TOKEN:
            logger.info(f"Webhook verified successfully")
            return int(challenge)
        else:
            logger.warning(f"Webhook verification failed. Token: {token}")
            return {"status": "error", "message": "Verification failed"}
    
    return {"status": "error", "message": "Missing parameters"}

@router.post("/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    """Recibir mensajes y eventos de Meta WhatsApp API"""
    try:
        data = await request.json()
        logger.info(f"=== WEBHOOK POST RECEIVED ===")
        logger.info(f"Full payload: {json.dumps(data)[:1000]}")
        
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
                        
                        logger.info(f"Message details - ID: {message_id}, From: {phone}, Body: {text}")
                        
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
                        
                        result = db.table("whatsapp_configs").select("tenant_id, phone_number_id").eq("phone_number_id", phone_number_id).execute()
                        
                        logger.info(f"Tenant lookup result: {result.data}")
                        
                        if result.data:
                            tenant_id = result.data[0]["tenant_id"]
                            
                            logger.info(f"✓ Message from {phone} to tenant {tenant_id}: {text}")
                            
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
        buffer_key = f"{tenant_id}:{phone}"
        if buffer_key not in _message_buffers:
            return
        
        buffer = _message_buffers[buffer_key]
        messages = buffer.messages.copy()
        message_ids = buffer.message_ids.copy()
        
        # Clear buffer
        del _message_buffers[buffer_key]
        
        if not messages:
            return
        
        # Join all messages with spaces
        combined_text = " ".join(messages)
        
        logger.info("=" * 60)
        logger.info(f"🔄 PROCESSING BUFFERED MESSAGES for {phone}")
        logger.info(f"   Total messages: {len(messages)}")
        logger.info(f"   Message IDs: {message_ids}")
        logger.info(f"   Combined text: {combined_text[:200]}...")
        logger.info("=" * 60)
        
        from services.whatsapp.meta_bot_service import bot_service
        from db.supabase import get_supabase_client
        
        # Obtener token del tenant
        db = get_supabase_client()
        result = db.table("whatsapp_configs").select("access_token").eq("tenant_id", tenant_id).execute()
        
        if not result.data:
            logger.error(f"No config found for tenant {tenant_id}")
            return
        
        token = result.data[0]["access_token"]
        
        # Crear instancia del servicio para responder
        service = MetaWhatsAppService(phone_number_id=phone_id, access_token=token)
        
        # Procesar mensaje combinado con el nuevo bot service
        logger.info(f"Calling bot_service.process_message with combined text...")
        response = await bot_service.process_message(tenant_id, phone, combined_text, phone_id)
        
        # Enviar respuesta
        if response:
            logger.info(f"Sending response to {phone}")
            service.send_message(phone, response)
        else:
            logger.warning(f"No response generated for combined message: {combined_text[:100]}")
            
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
        logger.info(f"📩 NEW MESSAGE from {phone}: {text[:50]}")
        
        buffer_key = f"{tenant_id}:{phone}"
        
        # Check if we have an existing buffer for this user
        if buffer_key in _message_buffers:
            buffer = _message_buffers[buffer_key]
            
            # Cancel existing timer
            if buffer.timer and not buffer.timer.done():
                buffer.timer.cancel()
                logger.info(f"⏹️ Cancelled existing timer for {phone}")
            
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
            logger.info(f"🆕 Created new buffer for {phone}")
        
        # Start new timer to process after delay
        async def delayed_process():
            await asyncio.sleep(BUFFER_TIMEOUT_SECONDS)
            logger.info(f"⏰ Timer expired for {phone}, processing buffered messages...")
            await _process_buffered_messages(tenant_id, phone, phone_id)
        
        # Store the timer task
        _message_buffers[buffer_key].timer = asyncio.create_task(delayed_process())
        
        logger.info(f"⏳ Timer started: {BUFFER_TIMEOUT_SECONDS}s wait for more messages...")
            
    except Exception as e:
        logger.error(f"ERROR in process_meta_message: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        # Fallback: process immediately on error
        try:
            from services.whatsapp.meta_bot_service import bot_service
            from db.supabase import get_supabase_client
            
            db = get_supabase_client()
            result = db.table("whatsapp_configs").select("access_token").eq("tenant_id", tenant_id).execute()
            
            if result.data:
                token = result.data[0]["access_token"]
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
    result = db.table("whatsapp_configs").select("*").eq("tenant_id", tenant["id"]).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="WhatsApp no configurado")
    
    config = result.data[0]
    
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
    result = db.table("whatsapp_configs").select("*").eq("tenant_id", tenant["id"]).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="WhatsApp no configurado")
    
    config = result.data[0]
    
    service = MetaWhatsAppService(
        phone_number_id=config["phone_number_id"],
        access_token=config["access_token"]
    )
    
    templates = service.get_templates()
    return templates

@router.delete("/config")
async def delete_whatsapp_config(tenant: dict = Depends(get_current_tenant)):
    """Eliminar configuración de WhatsApp"""
    from db.supabase import get_supabase_client
    
    db = get_supabase_client()
    db.table("whatsapp_configs").delete().eq("tenant_id", tenant["id"]).execute()
    
    return {"status": "deleted", "message": "Configuración eliminada"}
