from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, Any
import httpx
import json
from datetime import datetime
from config import get_settings

router = APIRouter()

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
async def whatsapp_webhook(webhook_data: WebhookMessage, background_tasks: BackgroundTasks):
    """Webhook para recibir mensajes de Evolution API"""
    
    try:
        # Procesar mensaje entrante
        message_type = webhook_data.message.get("messageType", "")
        sender = webhook_data.senderData.get("sender", "")
        instance_id = webhook_data.instance
        
        if message_type == "textMessage":
            message_text = webhook_data.message.get("textMessage", {}).get("text", "")
            
            # Agregar procesamiento en background usando el servicio del bot
            from services.whatsapp_bot import bot_service
            background_tasks.add_task(
                bot_service.process_message,
                sender,
                message_text,
                instance_id
            )
        
        return {"status": "received"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def get_whatsapp_health():
    """Verificar estado de Evolution API y conexión WhatsApp"""
    from services.whatsapp.evolution_service import evolution_service
    
    evolution_health = evolution_service.health_check()
    connection_status = evolution_service.get_connection_status()
    
    is_connected = connection_status.get("state") == "OPEN"
    needs_qr = not is_connected and evolution_health.get("status") == "online"
    
    # Log warning if disconnected
    if not is_connected:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"WhatsApp bot disconnected! Status: {connection_status}")
    
    return {
        "evolution_api": evolution_health,
        "whatsapp_connection": connection_status,
        "bot_status": "connected" if is_connected else "disconnected",
        "needs_qr": needs_qr,
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
