"""
WhatsApp API usando Meta (Facebook) WhatsApp Business API
Documentación: https://developers.facebook.com/docs/whatsapp/cloud-api
"""
import os
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any
import httpx
import json
from datetime import datetime
import logging

from api.deps import get_current_tenant
from services.whatsapp.meta_service import MetaWhatsAppService

router = APIRouter()
logger = logging.getLogger(__name__)

# Instancia del servicio Meta
meta_service = MetaWhatsAppService()

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
    """Verificar estado de la conexión con Meta API"""
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
    from db.supabase import get_supabase_client
    
    db = get_supabase_client()
    
    # Verificar credenciales antes de guardar
    service = MetaWhatsAppService(
        phone_number_id=data.phone_number_id,
        access_token=data.access_token
    )
    
    verification = service.verify_credentials()
    
    if not verification.get("valid"):
        raise HTTPException(
            status_code=400, 
            detail=f"Credenciales inválidas: {verification.get('error')}"
        )
    
    # Preparar datos
    config_data = {
        "tenant_id": tenant["id"],
        "phone_number_id": data.phone_number_id,
        "access_token": data.access_token,
        "business_account_id": data.business_account_id,
        "phone_number": data.phone_number,
        "is_connected": True,
        "provider": "meta",
        "updated_at": datetime.now().isoformat()
    }
    
    # Verificar si ya existe
    existing = db.table("whatsapp_configs").select("id").eq("tenant_id", tenant["id"]).execute()
    
    if existing.data:
        # Actualizar
        result = db.table("whatsapp_configs").update(config_data).eq("tenant_id", tenant["id"]).execute()
    else:
        # Crear nuevo
        config_data["created_at"] = datetime.now().isoformat()
        result = db.table("whatsapp_configs").insert(config_data).execute()
    
    return {
        "status": "success",
        "message": "WhatsApp configurado correctamente",
        "verified": True,
        "app": verification.get("name")
    }

@router.post("/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    """Recibir mensajes y eventos de Meta WhatsApp API"""
    try:
        data = await request.json()
        logger.info(f"Meta webhook received: {json.dumps(data)[:500]}...")
        
        # Procesar entries
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                
                # Mensajes entrantes
                if "messages" in value:
                    for message in value.get("messages", []):
                        phone = message.get("from")
                        text = message.get("text", {}).get("body", "")
                        
                        # Buscar tenant por número de teléfono
                        from db.supabase import get_supabase_client
                        db = get_supabase_client()
                        
                        # El phone_number_id viene en los metadata
                        metadata = value.get("metadata", {})
                        phone_number_id = metadata.get("phone_number_id")
                        
                        result = db.table("whatsapp_configs").select("tenant_id").eq("phone_number_id", phone_number_id).execute()
                        
                        if result.data:
                            tenant_id = result.data[0]["tenant_id"]
                            
                            logger.info(f"Message from {phone} to tenant {tenant_id}: {text}")
                            
                            # Procesar mensaje
                            background_tasks.add_task(
                                process_meta_message,
                                tenant_id,
                                phone,
                                text,
                                phone_number_id
                            )
                
                # Estados de mensajes
                if "statuses" in value:
                    for status in value.get("statuses", []):
                        logger.info(f"Message status: {status.get('id')} - {status.get('status')}")
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "error", "message": str(e)}

async def process_meta_message(tenant_id: str, phone: str, text: str, phone_id: str):
    """Procesar mensaje entrante usando el bot"""
    from services.whatsapp_bot import bot_service
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
    
    # Procesar mensaje
    response = await bot_service.process_message(tenant_id, phone, text)
    
    # Enviar respuesta
    if response:
        service.send_message(phone, response)

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
