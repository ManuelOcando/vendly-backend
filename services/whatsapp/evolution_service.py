import os
import requests
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

class BaileysService:
    """Servicio para comunicarse con Vendly Baileys (Node.js multi-tenant WhatsApp)"""
    
    def __init__(self):
        self.base_url = os.getenv("BAILEYS_SERVICE_URL", "https://vendly-baileys.up.railway.app")
        
    def health_check(self) -> Dict[str, Any]:
        """Verificar si servicio Baileys está activo"""
        try:
            response = requests.get(
                f"{self.base_url}/health",
                timeout=10
            )
            return {
                "status": "online" if response.status_code == 200 else "error",
                "code": response.status_code,
                "data": response.json() if response.status_code == 200 else None
            }
        except Exception as e:
            logger.error(f"Baileys health check failed: {e}")
            return {"status": "offline", "error": str(e)}
    
    def create_session(self, tenant_id: str, phone_number: str = None) -> Dict[str, Any]:
        """Crear sesión de WhatsApp para un tenant"""
        try:
            response = requests.post(
                f"{self.base_url}/session/create",
                json={
                    "tenant_id": tenant_id,
                    "phone_number": phone_number
                },
                timeout=30
            )
            return response.json()
        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            return {"error": str(e)}
    
    def get_qr_code(self, tenant_id: str) -> Optional[str]:
        """Obtener QR para escanear"""
        try:
            response = requests.get(
                f"{self.base_url}/session/qr/{tenant_id}",
                timeout=10
            )
            data = response.json()
            return data.get("qr_base64")
        except Exception as e:
            logger.error(f"Failed to get QR: {e}")
            return None
    
    def get_connection_status(self, tenant_id: str) -> Dict[str, Any]:
        """Verificar estado de conexión de WhatsApp"""
        try:
            response = requests.get(
                f"{self.base_url}/session/status/{tenant_id}",
                timeout=10
            )
            data = response.json()
            
            # Mapear estado de Baileys a formato consistente
            status = data.get("status", {})
            state = status.get("state", "DISCONNECTED")
            
            return {
                "state": state,
                "connected": state == "CONNECTED",
                "has_qr": data.get("qr") is not None
            }
        except Exception as e:
            logger.error(f"Failed to get connection status: {e}")
            return {"state": "DISCONNECTED", "error": str(e)}
    
    def send_message(self, tenant_id: str, phone: str, message: str) -> Dict[str, Any]:
        """Enviar mensaje de WhatsApp"""
        # Normalizar número
        number = phone.replace("+", "").replace("-", "").replace(" ", "")
        if not number.startswith("58"):  # Venezuela
            number = f"58{number}"
        
        try:
            response = requests.post(
                f"{self.base_url}/message/send",
                json={
                    "tenant_id": tenant_id,
                    "phone": number,
                    "message": message
                },
                timeout=30
            )
            return response.json()
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return {"error": str(e)}
    
    def disconnect(self, tenant_id: str) -> Dict[str, Any]:
        """Cerrar sesión de WhatsApp"""
        try:
            response = requests.delete(
                f"{self.base_url}/session/{tenant_id}",
                timeout=10
            )
            return response.json()
        except Exception as e:
            logger.error(f"Failed to disconnect: {e}")
            return {"error": str(e)}

# Backward compatibility
class TenantEvolutionService(BaileysService):
    """Alias for backward compatibility"""
    pass

# Singleton instances
baileys_service = BaileysService()
evolution_service = baileys_service  # For backward compatibility
