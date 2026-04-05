from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any
import httpx
import json
from datetime import datetime
from config import get_settings
import logging

from api.deps import get_current_tenant

router = APIRouter()
logger = logging.getLogger(__name__)

# Evolution API configuration
settings = get_settings()
EVOLUTION_API_URL = settings.EVOLUTION_API_URL
EVOLUTION_API_KEY = settings.EVOLUTION_API_KEY

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

@router.post("/connect")
async def connect_whatsapp(connection: WhatsAppConnection):
    """Conectar una instancia de WhatsApp vía QR"""
    
    try:
        # Crear instancia en Evolution API
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{EVOLUTION_API_URL}/instance/create",
                headers={"apikey": EVOLUTION_API_KEY},
                json={
                    "instanceName": connection.instance_name,
                    "qrcode": True,
                    "number": connection.phone_number
                }
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail="Error creating WhatsApp instance"
                )
            
            instance_data = response.json()
            
            # Guardar conexión en base de datos
            # TODO: Implementar guardado en Supabase
            
            return {
                "status": "success",
                "instance_id": instance_data.get("instance"),
                "qrcode": instance_data.get("qrcode", {}).get("base64"),
                "message": "QR code generated. Scan with WhatsApp."
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/send-message")
async def send_whatsapp_message(message: WhatsAppMessage):
    """Enviar mensaje vía Evolution API"""
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{EVOLUTION_API_URL}/message/sendText/{message.instance_id}",
                headers={"apikey": EVOLUTION_API_KEY},
                json={
                    "number": message.to,
                    "text": message.message
                }
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail="Error sending message"
                )
            
            return response.json()
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/webhook")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    """Webhook para recibir mensajes de Evolution API - Multi-tenant"""
    try:
        data = await request.json()
        logger.info(f"Webhook received: {data}")
        
        # Extraer instance del webhook para identificar tenant
        instance = data.get("instance", "")
        event = data.get("event")
        
        # Buscar tenant por instance_name
        from db.supabase import get_supabase_client
        db = get_supabase_client()
        result = db.table("whatsapp_configs").select("tenant_id").eq("instance_name", instance).execute()
        
        if not result.data:
            logger.warning(f"No tenant found for instance: {instance}")
            return {"status": "ignored", "reason": "unknown_instance"}
        
        tenant_id = result.data[0]["tenant_id"]
        
        if event == "messages.upsert":
            message_data = data.get("data", {})
            message = message_data.get("message", {})
            
            if message.get("conversation"):
                phone = message_data.get("key", {}).get("remoteJid", "").split("@")[0]
                text = message.get("conversation")
                
                logger.info(f"Message from {phone} to tenant {tenant_id}: {text}")
                
                # Procesar mensaje con bot del tenant
                background_tasks.add_task(
                    process_tenant_message,
                    tenant_id,
                    phone,
                    text
                )
                
        elif event == "connection.update":
            state = data.get("data", {}).get("state")
            logger.info(f"Connection state for {tenant_id}: {state}")
            
            # Actualizar estado en DB
            db.table("whatsapp_configs").update({
                "is_connected": state == "OPEN",
                "updated_at": datetime.now().isoformat()
            }).eq("tenant_id", tenant_id).execute()
        
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "error", "message": str(e)}

async def process_tenant_message(tenant_id: str, phone: str, text: str):
    """Procesar mensaje para un tenant específico"""
    from services.whatsapp_bot import bot_service
    await bot_service.process_message(tenant_id, phone, text)

@router.get("/health")
async def get_whatsapp_health(tenant: dict = Depends(get_current_tenant)):
    """Verificar estado de WhatsApp para el tenant actual"""
    from db.supabase import get_supabase_client
    from services.whatsapp.evolution_service import TenantEvolutionService
    
    db = get_supabase_client()
    
    # Obtener config del tenant
    result = db.table("whatsapp_configs").select("*").eq("tenant_id", tenant["id"]).execute()
    
    if not result.data:
        return {
            "configured": False,
            "message": "WhatsApp no configurado. Sigue la guía de setup."
        }
    
    config = result.data[0]
    
    # Crear servicio para este tenant
    service = TenantEvolutionService(
        tenant_id=tenant["id"],
        evolution_url=config["evolution_api_url"],
        api_key=config["evolution_api_key"],
        instance_name=config["instance_name"]
    )
    
    evolution_health = service.health_check()
    connection_status = service.get_connection_status()
    
    is_connected = connection_status.get("state") == "OPEN"
    
    return {
        "configured": True,
        "evolution_api": evolution_health,
        "whatsapp_connection": connection_status,
        "bot_status": "connected" if is_connected else "disconnected",
        "needs_qr": not is_connected and evolution_health.get("status") == "online",
        "instance": config["instance_name"],
        "timestamp": datetime.now().isoformat()
    }

async def process_whatsapp_message(sender: str, message: str, instance_id: str):
    """Función obsoleta - usar WhatsAppBotService en su lugar"""
    pass

@router.get("/instances")
async def list_instances():
    """Listar todas las instancias activas"""
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{EVOLUTION_API_URL}/instance/fetchInstances",
                headers={"apikey": EVOLUTION_API_KEY}
            )
            
            return response.json()
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/disconnect/{instance_id}")
async def disconnect_whatsapp(instance_id: str):
    """Desconectar instancia de WhatsApp"""
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{EVOLUTION_API_URL}/instance/logout/{instance_id}",
                headers={"apikey": EVOLUTION_API_KEY}
            )
            
            # TODO: Eliminar conexión de base de datos
            
            return {"status": "disconnected"}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
