from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import uuid
import redis
import json

router = APIRouter()

# Redis connection for cart locks and temporary data
# TODO: Configurar Redis en producción
REDIS_CLIENT = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

class CartItem(BaseModel):
    item_id: str
    quantity: int
    price: float
    name: str

class Cart(BaseModel):
    id: str
    store_id: str
    items: List[CartItem]
    total: float
    customer_phone: Optional[str] = None
    status: str = "active"  # active, expired, converted
    expires_at: datetime

class CreateCartRequest(BaseModel):
    store_id: str
    items: List[CartItem]

class AddItemRequest(BaseModel):
    item_id: str
    quantity: int
    price: float
    name: str

@router.post("/create")
async def create_cart(request: CreateCartRequest):
    """Crear nuevo carrito"""
    
    try:
        cart_id = str(uuid.uuid4())
        total = sum(item.price * item.quantity for item in request.items)
        
        cart = Cart(
            id=cart_id,
            store_id=request.store_id,
            items=request.items,
            total=total,
            expires_at=datetime.utcnow() + timedelta(minutes=15)
        )
        
        # Guardar en Redis con TTL de 15 minutos
        cart_data = cart.model_dump_json()
        REDIS_CLIENT.setex(f"cart:{cart_id}", 900, cart_data)  # 900 seconds = 15 min
        
        # Bloquear stock en Redis
        for item in request.items:
            stock_key = f"stock_lock:{request.store_id}:{item.item_id}"
            REDIS_CLIENT.incrby(stock_key, item.quantity)
            REDIS_CLIENT.expire(stock_key, 900)  # 15 min
        
        return {
            "cart_id": cart_id,
            "total": total,
            "expires_at": cart.expires_at.isoformat(),
            "message": "Cart created successfully"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{cart_id}")
async def get_cart(cart_id: str):
    """Obtener carrito por ID"""
    
    try:
        cart_data = REDIS_CLIENT.get(f"cart:{cart_id}")
        
        if not cart_data:
            raise HTTPException(status_code=404, detail="Cart not found or expired")
        
        cart = json.loads(cart_data)
        
        # Verificar si no ha expirado
        expires_at = datetime.fromisoformat(cart["expires_at"])
        if datetime.utcnow() > expires_at:
            # Liberar locks de stock
            await release_stock_locks(cart["store_id"], cart["items"])
            REDIS_CLIENT.delete(f"cart:{cart_id}")
            raise HTTPException(status_code=410, detail="Cart expired")
        
        return cart
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{cart_id}/items")
async def add_to_cart(cart_id: str, request: AddItemRequest):
    """Agregar item al carrito existente"""
    
    try:
        cart_data = REDIS_CLIENT.get(f"cart:{cart_id}")
        
        if not cart_data:
            raise HTTPException(status_code=404, detail="Cart not found or expired")
        
        cart = json.loads(cart_data)
        
        # Verificar expiración
        expires_at = datetime.fromisoformat(cart["expires_at"])
        if datetime.utcnow() > expires_at:
            raise HTTPException(status_code=410, detail="Cart expired")
        
        # Buscar si el item ya existe
        existing_item = None
        for item in cart["items"]:
            if item["item_id"] == request.item_id:
                existing_item = item
                break
        
        if existing_item:
            # Actualizar cantidad
            existing_item["quantity"] += request.quantity
        else:
            # Agregar nuevo item
            new_item = {
                "item_id": request.item_id,
                "quantity": request.quantity,
                "price": request.price,
                "name": request.name
            }
            cart["items"].append(new_item)
        
        # Recalcular total
        cart["total"] = sum(item["price"] * item["quantity"] for item in cart["items"])
        
        # Actualizar locks de stock
        stock_key = f"stock_lock:{cart['store_id']}:{request.item_id}"
        REDIS_CLIENT.incrby(stock_key, request.quantity)
        REDIS_CLIENT.expire(stock_key, 900)
        
        # Guardar carrito actualizado
        REDIS_CLIENT.setex(f"cart:{cart_id}", 900, json.dumps(cart))
        
        return {
            "cart": cart,
            "message": "Item added to cart"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{cart_id}/customer")
async def set_customer_phone(cart_id: str, phone: str):
    """Establecer teléfono del cliente"""
    
    try:
        cart_data = REDIS_CLIENT.get(f"cart:{cart_id}")
        
        if not cart_data:
            raise HTTPException(status_code=404, detail="Cart not found or expired")
        
        cart = json.loads(cart_data)
        cart["customer_phone"] = phone
        
        REDIS_CLIENT.setex(f"cart:{cart_id}", 900, json.dumps(cart))
        
        return {"message": "Customer phone updated"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{cart_id}")
async def delete_cart(cart_id: str):
    """Eliminar carrito y liberar locks de stock"""
    
    try:
        cart_data = REDIS_CLIENT.get(f"cart:{cart_id}")
        
        if cart_data:
            cart = json.loads(cart_data)
            # Liberar locks de stock
            await release_stock_locks(cart["store_id"], cart["items"])
        
        REDIS_CLIENT.delete(f"cart:{cart_id}")
        
        return {"message": "Cart deleted successfully"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def release_stock_locks(store_id: str, items: List[Dict[str, Any]]):
    """Liberar locks de stock"""
    
    for item in items:
        stock_key = f"stock_lock:{store_id}:{item['item_id']}"
        REDIS_CLIENT.decrby(stock_key, item["quantity"])

@router.get("/{cart_id}/stock-status")
async def get_cart_stock_status(cart_id: str):
    """Verificar disponibilidad de stock para items del carrito"""
    
    try:
        cart_data = REDIS_CLIENT.get(f"cart:{cart_id}")
        
        if not cart_data:
            raise HTTPException(status_code=404, detail="Cart not found or expired")
        
        cart = json.loads(cart_data)
        stock_status = []
        
        # TODO: Verificar stock real en base de datos
        # Por ahora, asumimos que hay stock disponible
        
        for item in cart["items"]:
            locked_quantity = int(REDIS_CLIENT.get(f"stock_lock:{cart['store_id']}:{item['item_id']}") or 0)
            
            stock_status.append({
                "item_id": item["item_id"],
                "name": item["name"],
                "requested_quantity": item["quantity"],
                "locked_quantity": locked_quantity,
                "available": True  # TODO: Consultar stock real en DB
            })
        
        return {
            "cart_id": cart_id,
            "stock_status": stock_status,
            "all_available": all(item["available"] for item in stock_status)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
