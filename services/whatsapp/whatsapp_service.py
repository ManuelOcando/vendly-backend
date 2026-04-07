"""
Servicio WhatsApp - Ahora usa Meta API (reemplaza Evolution/Baileys)
"""
import os
import requests
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

class MetaWhatsAppService:
    """Servicio para Meta WhatsApp Cloud API - Multi-tenant"""
    
    BASE_URL = "https://graph.facebook.com/v18.0"
    
    def __init__(self, phone_number_id: str = None, access_token: str = None):
        self.phone_number_id = phone_number_id or os.getenv("META_WHATSAPP_PHONE_ID")
        self.access_token = access_token or os.getenv("META_WHATSAPP_TOKEN")
        self.business_account_id = os.getenv("META_WHATSAPP_BUSINESS_ID")
        
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
    
    def _url(self, endpoint: str = "") -> str:
        return f"{self.BASE_URL}/{self.phone_number_id}{endpoint}"
    
    def health_check(self) -> Dict[str, Any]:
        """Verificar que la API responde"""
        try:
            response = requests.get(
                f"{self.BASE_URL}/me",
                headers=self._headers(),
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "status": "online",
                    "connected": True,
                    "app_id": data.get("id"),
                    "name": data.get("name")
                }
            else:
                error = response.json().get("error", {})
                return {
                    "status": "error",
                    "connected": False,
                    "error": error.get("message", "Unknown error")
                }
        except Exception as e:
            logger.error(f"Meta API health check failed: {e}")
            return {"status": "offline", "connected": False, "error": str(e)}
    
    def send_message(self, phone: str, message: str) -> Dict[str, Any]:
        """Enviar mensaje de texto"""
        # Formatear número
        number = phone.replace("+", "").replace("-", "").replace(" ", "")
        if not number.startswith("58"):  # Venezuela por defecto
            number = f"58{number}"
        
        try:
            response = requests.post(
                self._url("/messages"),
                headers=self._headers(),
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": number,
                    "type": "text",
                    "text": {"body": message, "preview_url": False}
                },
                timeout=30
            )
            
            data = response.json()
            
            if response.status_code == 200:
                return {
                    "status": "sent",
                    "message_id": data.get("messages", [{}])[0].get("id"),
                    "recipient": number
                }
            else:
                error = data.get("error", {})
                logger.error(f"Meta API error: {error}")
                return {
                    "status": "failed",
                    "error": error.get("message", "Unknown error")
                }
                
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return {"status": "failed", "error": str(e)}
    
    def get_connection_status(self) -> Dict[str, Any]:
        """Meta API siempre está 'conectada' si el token es válido"""
        health = self.health_check()
        return {
            "state": "CONNECTED" if health.get("connected") else "DISCONNECTED",
            "connected": health.get("connected"),
            "status": health
        }

# Alias para compatibilidad
class WhatsAppService(MetaWhatsAppService):
    pass

# Singleton para uso global
whatsapp_service = MetaWhatsAppService()
