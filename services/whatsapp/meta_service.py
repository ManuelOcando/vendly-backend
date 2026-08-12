"""
Servicio para Meta WhatsApp Business API
Documentación: https://developers.facebook.com/docs/whatsapp/cloud-api
"""
import os
import re
import requests

from db.whatsapp_config import fetch_config
from typing import Optional, Dict, Any
import logging
from utils.log_privacy import tel

logger = logging.getLogger(__name__)

class MetaWhatsAppService:
    """Servicio para interactuar con Meta WhatsApp Cloud API"""
    
    BASE_URL = "https://graph.facebook.com/v18.0"
    
    @classmethod
    def for_tenant(cls, db, tenant_id: str) -> Optional["MetaWhatsAppService"]:
        """This tenant's own Meta credentials, or None if it has none usable.

        Constructing MetaWhatsAppService() with no arguments falls back to the
        META_WHATSAPP_* environment variables, which in a multi-tenant backend
        means sending every message from one tenant's number. Returning None here
        instead is deliberate: not sending is better than sending from the wrong
        business.

        `db` is passed in rather than fetched so callers share their client and
        tests can hand over a fake.
        """
        try:
            config = fetch_config(db, tenant_id, "phone_number_id, access_token")
        except Exception as e:
            logger.error(
                "Could not read WhatsApp credentials for tenant %s: %s",
                tenant_id, e, exc_info=True,
            )
            return None

        if not config:
            logger.error("Tenant %s has no whatsapp_configs row", tenant_id)
            return None

        phone_number_id = config.get("phone_number_id")
        access_token = config.get("access_token")

        if not phone_number_id or not access_token:
            logger.error(
                "Tenant %s has an incomplete WhatsApp config "
                "(phone_number_id=%s, access_token=%s)",
                tenant_id, bool(phone_number_id), bool(access_token),
            )
            return None

        return cls(phone_number_id=phone_number_id, access_token=access_token)

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

    def normalize_phone(self, phone: str) -> str:
        """Normalizar número de teléfono eliminando +, - y espacios"""
        return re.sub(r'[\+\-\s]', '', phone)
    
    def verify_credentials(self) -> Dict[str, Any]:
        """Verificar que las credenciales son válidas"""
        try:
            # Sin el prefijo del token: quince caracteres no bastan para usarlo,
            # pero es un fragmento de credencial en un log que va a Render.
            logger.info(
                "Verifying credentials - Phone ID: %s, token presente: %s",
                self.phone_number_id, bool(self.access_token),
            )
            
            response = requests.get(
                f"{self.BASE_URL}/me",
                headers=self._headers(),
                timeout=10
            )
            data = response.json()
            
            logger.info(f"Meta API response - Status: {response.status_code}, Data: {data}")
            
            if response.status_code == 200:
                return {
                    "valid": True,
                    "app_id": data.get("id"),
                    "name": data.get("name")
                }
            else:
                error_msg = data.get("error", {}).get("message", "Unknown error")
                error_code = data.get("error", {}).get("code", "")
                error_type = data.get("error", {}).get("type", "")
                
                # Traducir errores comunes
                if error_code == 190:
                    error_msg = "Token inválido o expirado. Genera un nuevo token en Meta Business."
                elif error_code == 100:
                    error_msg = "App no encontrada. Verifica que el App ID sea correcto."
                elif "expired" in error_msg.lower():
                    error_msg = "Token expirado. Necesitas generar uno nuevo."
                
                logger.error(f"Meta API error: {error_msg} (code: {error_code}, type: {error_type})")
                
                return {
                    "valid": False,
                    "error": error_msg,
                    "code": error_code,
                    "type": error_type,
                    "raw_response": data
                }
        except requests.exceptions.Timeout:
            logger.error("Meta API timeout")
            return {"valid": False, "error": "Timeout - Meta API no responde"}
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
    
    def send_message(self, to: str, message: str) -> Dict[str, Any]:
        """Enviar mensaje de texto simple"""
        logger.info(f"=== SENDING MESSAGE ===")
        logger.info("To: %s, Message length: %d", tel(to), len(message))
        logger.info(f"Using phone_number_id: {self.phone_number_id}")
        logger.info(f"Token presente: {bool(self.access_token)}")

        phone = self.normalize_phone(to)
        logger.info("Formatted phone: %s", tel(phone))

        try:
            url = self._url("/messages")
            logger.info(f"API URL: {url}")

            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": phone,
                "type": "text",
                "text": {
                    "body": message,
                    "preview_url": False
                }
            }
            # El payload lleva destinatario y texto del mensaje; solo su forma.
            logger.info("Payload: destinatario=%s, tipo=%s", tel(payload.get("to")), payload.get("type"))

            response = requests.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=30
            )

            data = response.json()
            logger.info(f"Meta API response status: {response.status_code}")
            logger.info(f"Meta API response: {data}")

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
                    "error": data.get("error", {}).get("message", "Unknown error"),
                    "code": data.get("error", {}).get("code", ""),
                    "details": data
                }

        except requests.exceptions.Timeout:
            logger.error("Timeout sending message to %s", tel(phone))
            return {"status": "failed", "error": "Timeout"}
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"status": "failed", "error": str(e)}

    def send_text_message(self, to: str, message: str) -> Dict[str, Any]:
        """Alias de send_message para compatibilidad hacia atrás"""
        return self.send_message(to, message)
    
    def send_template_message(self, to: str, template_name: str, language: str = "es", components: list = None) -> Dict[str, Any]:
        """Enviar mensaje usando plantilla aprobada"""
        phone = self.normalize_phone(to)
        
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
