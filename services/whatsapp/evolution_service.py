import os
import requests
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

class EvolutionAPIService:
    def __init__(self):
        self.base_url = os.getenv("EVOLUTION_API_URL", "https://vendly-evolution.onrender.com")
        self.api_key = os.getenv("EVOLUTION_API_KEY", "")
        self.instance_name = os.getenv("EVOLUTION_INSTANCE_NAME", "vendly-bot")
        
    def _headers(self) -> Dict[str, str]:
        return {
            "apikey": self.api_key,
            "Content-Type": "application/json"
        }
    
    def health_check(self) -> Dict[str, Any]:
        """Verificar si Evolution API está activo"""
        try:
            response = requests.get(
                f"{self.base_url}/health",
                timeout=10
            )
            return {
                "status": "online" if response.status_code == 200 else "error",
                "code": response.status_code
            }
        except Exception as e:
            logger.error(f"Evolution API health check failed: {e}")
            return {"status": "offline", "error": str(e)}
    
    def create_instance(self) -> Dict[str, Any]:
        """Crear instancia de WhatsApp"""
        try:
            response = requests.post(
                f"{self.base_url}/instance/create",
                headers=self._headers(),
                json={
                    "instanceName": self.instance_name,
                    "token": os.getenv("EVOLUTION_INSTANCE_TOKEN", "vendly-token"),
                    "qrcode": True,
                    "number": "",
                    "webhook": {
                        "url": f"{os.getenv('BACKEND_URL', 'https://vendly-backend-uuos.onrender.com')}/webhook/whatsapp",
                        "enabled": True,
                        "events": ["messages.upsert", "connection.update"]
                    }
                },
                timeout=30
            )
            return response.json()
        except Exception as e:
            logger.error(f"Failed to create instance: {e}")
            return {"error": str(e)}
    
    def get_qr_code(self) -> Optional[str]:
        """Obtener QR para escanear"""
        try:
            response = requests.get(
                f"{self.base_url}/instance/connect/{self.instance_name}",
                headers=self._headers(),
                timeout=10
            )
            data = response.json()
            if "qrcode" in data and data["qrcode"]:
                return data["qrcode"]["base64"]  # QR en base64
            return None
        except Exception as e:
            logger.error(f"Failed to get QR: {e}")
            return None
    
    def get_connection_status(self) -> Dict[str, Any]:
        """Verificar estado de conexión de WhatsApp"""
        try:
            response = requests.get(
                f"{self.base_url}/instance/connectionState/{self.instance_name}",
                headers=self._headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get connection status: {e}")
            return {"state": "DISCONNECTED", "error": str(e)}
    
    def send_text_message(self, phone: str, message: str) -> Dict[str, Any]:
        """Enviar mensaje de texto"""
        # Normalizar número
        number = phone.replace("+", "").replace("-", "").replace(" ", "")
        if not number.startswith("58"):  # Venezuela
            number = f"58{number}"
        
        try:
            response = requests.post(
                f"{self.base_url}/message/sendText/{self.instance_name}",
                headers=self._headers(),
                json={
                    "number": number,
                    "text": message,
                    "options": {
                        "delay": 1200,
                        "presence": "composing"
                    }
                },
                timeout=30
            )
            return response.json()
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return {"error": str(e)}
    
    def logout(self) -> Dict[str, Any]:
        """Cerrar sesión de WhatsApp"""
        try:
            response = requests.delete(
                f"{self.base_url}/instance/logout/{self.instance_name}",
                headers=self._headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            logger.error(f"Failed to logout: {e}")
            return {"error": str(e)}

class TenantEvolutionService:
    """Servicio para múltiples tenants - cada uno con su propio bot"""
    
    def __init__(self, tenant_id: str, evolution_url: str, api_key: str, instance_name: str = "vendly-bot"):
        self.tenant_id = tenant_id
        self.base_url = evolution_url.rstrip("/")
        self.api_key = api_key
        self.instance_name = instance_name
        
    def _headers(self) -> Dict[str, str]:
        return {
            "apikey": self.api_key,
            "Content-Type": "application/json"
        }
    
    def health_check(self) -> Dict[str, Any]:
        """Verificar si Evolution API del tenant está activo"""
        try:
            response = requests.get(
                f"{self.base_url}/health",
                timeout=10
            )
            return {
                "status": "online" if response.status_code == 200 else "error",
                "code": response.status_code
            }
        except Exception as e:
            logger.error(f"Tenant {self.tenant_id} Evolution API health check failed: {e}")
            return {"status": "offline", "error": str(e)}
    
    def get_connection_status(self) -> Dict[str, Any]:
        """Verificar estado de conexión WhatsApp del tenant"""
        try:
            response = requests.get(
                f"{self.base_url}/instance/connectionState/{self.instance_name}",
                headers=self._headers(),
                timeout=10
            )
            return response.json()
        except Exception as e:
            logger.error(f"Tenant {self.tenant_id} connection check failed: {e}")
            return {"state": "DISCONNECTED", "error": str(e)}
    
    def send_message(self, phone: str, message: str) -> Dict[str, Any]:
        """Enviar mensaje desde el bot del tenant"""
        number = phone.replace("+", "").replace("-", "").replace(" ", "")
        if not number.startswith("58"):
            number = f"58{number}"
        
        try:
            response = requests.post(
                f"{self.base_url}/message/sendText/{self.instance_name}",
                headers=self._headers(),
                json={
                    "number": number,
                    "text": message,
                    "options": {"delay": 1200, "presence": "composing"}
                },
                timeout=30
            )
            return response.json()
        except Exception as e:
            logger.error(f"Tenant {self.tenant_id} failed to send message: {e}")
            return {"error": str(e)}
