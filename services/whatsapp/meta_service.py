"""
Servicio para Meta WhatsApp Business API
Documentación: https://developers.facebook.com/docs/whatsapp/cloud-api
"""
import os
import requests
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

class MetaWhatsAppService:
    """Servicio para interactuar con Meta WhatsApp Cloud API"""
    
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
    
    def _url(self, endpoint: str) -> str:
        return f"{self.BASE_URL}/{self.phone_number_id}{endpoint}"
    
    def verify_credentials(self) -> Dict[str, Any]:
        """Verificar que las credenciales son válidas"""
        try:
            response = requests.get(
                f"{self.BASE_URL}/me",
                headers=self._headers(),
                timeout=10
            )
            data = response.json()
            
            if response.status_code == 200:
                return {
                    "valid": True,
                    "app_id": data.get("id"),
                    "name": data.get("name")
                }
            else:
                return {
                    "valid": False,
                    "error": data.get("error", {}).get("message", "Unknown error")
                }
        except Exception as e:
            logger.error(f"Credential verification failed: {e}")
            return {"valid": False, "error": str(e)}
    
    def health_check(self) -> Dict[str, Any]:
        """Verificar el estado de la conexión con Meta API"""
        try:
            # Verificar credenciales básicas
            verification = self.verify_credentials()
            if not verification.get("valid"):
                return {
                    "connected": False,
                    "status": "invalid_credentials",
                    "error": verification.get("error")
                }
            
            # Obtener información del número de teléfono
            if self.phone_number_id:
                response = requests.get(
                    f"{self.BASE_URL}/{self.phone_number_id}",
                    headers=self._headers(),
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "connected": True,
                        "status": "active",
                        "name": verification.get("name"),
                        "phone_number_id": self.phone_number_id,
                        "display_phone_number": data.get("display_phone_number")
                    }
                else:
                    return {
                        "connected": False,
                        "status": "phone_not_found",
                        "error": "Phone number ID not found or not accessible"
                    }
            else:
                return {
                    "connected": False,
                    "status": "no_phone_id",
                    "error": "Phone number ID not configured"
                }
                
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "connected": False,
                "status": "error",
                "error": str(e)
            }
    
    def get_phone_numbers(self) -> Dict[str, Any]:
        """Obtener números de teléfono asociados a la cuenta"""
        try:
            response = requests.get(
                f"{self.BASE_URL}/{self.business_account_id}/phone_numbers",
                headers=self._headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get phone numbers: {e}")
            return {"error": str(e)}
    
    def send_text_message(self, to: str, message: str) -> Dict[str, Any]:
        """Enviar mensaje de texto"""
        # Formatear número (quitar + si existe)
        phone = to.replace("+", "").replace("-", "").replace(" ", "")
        
        try:
            response = requests.post(
                self._url("/messages"),
                headers=self._headers(),
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": phone,
                    "type": "text",
                    "text": {
                        "body": message,
                        "preview_url": False
                    }
                },
                timeout=30
            )
            
            data = response.json()
            
            if response.status_code == 200:
                return {
                    "status": "sent",
                    "message_id": data.get("messages", [{}])[0].get("id"),
                    "recipient": phone
                }
            else:
                logger.error(f"Meta API error: {data}")
                return {
                    "status": "failed",
                    "error": data.get("error", {}).get("message", "Unknown error")
                }
                
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return {"status": "failed", "error": str(e)}
    
    def send_message(self, to: str, message: str) -> Dict[str, Any]:
        """Alias para send_text_message - enviar mensaje de texto"""
        return self.send_text_message(to, message)
    
    def send_template_message(self, to: str, template_name: str, language: str = "es", components: list = None) -> Dict[str, Any]:
        """Enviar mensaje usando plantilla aprobada"""
        phone = to.replace("+", "").replace("-", "").replace(" ", "")
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language}
            }
        }
        
        if components:
            payload["template"]["components"] = components
        
        try:
            response = requests.post(
                self._url("/messages"),
                headers=self._headers(),
                json=payload,
                timeout=30
            )
            
            data = response.json()
            
            if response.status_code == 200:
                return {
                    "status": "sent",
                    "message_id": data.get("messages", [{}])[0].get("id")
                }
            else:
                return {
                    "status": "failed",
                    "error": data.get("error", {}).get("message", "Unknown error")
                }
                
        except Exception as e:
            logger.error(f"Failed to send template: {e}")
            return {"status": "failed", "error": str(e)}
    
    def get_message_status(self, message_id: str) -> Dict[str, Any]:
        """Obtener estado de un mensaje enviado"""
        try:
            response = requests.get(
                f"{self.BASE_URL}/{message_id}",
                headers=self._headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get message status: {e}")
            return {"error": str(e)}
    
    def get_templates(self) -> Dict[str, Any]:
        """Obtener plantillas de mensajes aprobadas"""
        try:
            response = requests.get(
                f"{self.BASE_URL}/{self.business_account_id}/message_templates",
                headers=self._headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get templates: {e}")
            return {"error": str(e)}
    
    def download_media(self, media_id: str) -> Dict[str, Any]:
        """Descargar archivo multimedia recibido"""
        try:
            # Primero obtener URL
            response = requests.get(
                f"{self.BASE_URL}/{media_id}",
                headers=self._headers(),
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                media_url = data.get("url")
                
                # Descargar contenido
                media_response = requests.get(media_url, headers=self._headers(), timeout=30)
                
                return {
                    "success": True,
                    "content": media_response.content,
                    "mime_type": data.get("mime_type"),
                    "filename": f"media_{media_id}"
                }
            else:
                return {"success": False, "error": "Failed to get media URL"}
                
        except Exception as e:
            logger.error(f"Failed to download media: {e}")
            return {"success": False, "error": str(e)}

# Instancia por defecto
meta_whatsapp_service = MetaWhatsAppService()
