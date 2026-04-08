"""
Base handlers for WhatsApp bot using Chain of Responsibility pattern
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class MessageHandler(ABC):
    """Base class for message handlers"""
    
    def __init__(self, next_handler=None):
        self.next_handler = next_handler
    
    @abstractmethod
    async def can_handle(self, message_data: Dict[str, Any]) -> bool:
        """Check if this handler can process the message"""
        pass
    
    @abstractmethod
    async def handle(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Process the message and return response"""
        pass
    
    async def process(self, message_data: Dict[str, Any]) -> Optional[str]:
        """Process message through the chain"""
        if await self.can_handle(message_data):
            response = await self.handle(message_data)
            if response:
                return response
        
        if self.next_handler:
            return await self.next_handler.process(message_data)
        
        return None

class BaseWhatsAppHandler(MessageHandler):
    """Base handler with common functionality"""
    
    def __init__(self, db_client, next_handler=None):
        super().__init__(next_handler)
        self.db = db_client
    
    async def get_tenant_config(self, tenant_id: str) -> Dict[str, Any]:
        """Get tenant configuration"""
        try:
            result = self.db.table("whatsapp_configs").select("*").eq("tenant_id", tenant_id).execute()
            return result.data[0] if result.data else {}
        except Exception as e:
            logger.error(f"Error getting tenant config: {e}")
            return {}
    
    async def get_session(self, tenant_id: str, phone: str) -> Dict[str, Any]:
        """Get or create conversation session"""
        try:
            # Try to get existing session
            result = self.db.table("conversation_sessions").select("*").eq(
                "tenant_id", tenant_id
            ).eq("customer_phone", phone).execute()
            
            if result.data:
                session = result.data[0]
                # Update last message time
                self.db.table("conversation_sessions").update({
                    "last_message_at": datetime.now().isoformat()
                }).eq("id", session["id"]).execute()
                return session
            
            # Create new session
            session_data = {
                "tenant_id": tenant_id,
                "customer_phone": phone,
                "current_state": "initial"
            }
            
            result = self.db.table("conversation_sessions").insert(session_data).execute()
            return result.data[0] if result.data else {}
            
        except Exception as e:
            logger.error(f"Error managing session: {e}")
            return {}
    
    async def update_session_state(self, session_id: str, state: str, data: Dict = None):
        """Update session state and data"""
        try:
            update_data = {
                "current_state": state,
                "updated_at": datetime.now().isoformat()
            }
            if data:
                update_data["session_data"] = data
            
            self.db.table("conversation_sessions").update(update_data).eq("id", session_id).execute()
        except Exception as e:
            logger.error(f"Error updating session: {e}")
