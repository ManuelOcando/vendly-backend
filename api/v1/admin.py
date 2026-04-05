from fastapi import APIRouter, HTTPException, Depends
from api.deps import get_current_user
from db.supabase import get_supabase_client
import os
import logging

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)

@router.post("/apply-migrations")
async def apply_migrations(user: dict = Depends(get_current_user)):
    """Aplicar migraciones pendientes en la base de datos"""
    try:
        db = get_supabase_client()
        
        # Leer archivo de migración
        migration_path = os.path.join(os.path.dirname(__file__), "..", "..", "db", "migrations", "004_whatsapp_configs.sql")
        
        with open(migration_path, "r") as f:
            sql = f.read()
        
        # Ejecutar SQL
        # Nota: Supabase Python client no soporta raw SQL directamente
        # Por eso usamos la REST API
        result = db.rpc("exec_sql", {"sql": sql}).execute()
        
        return {
            "status": "success",
            "message": "Migración aplicada correctamente",
            "migration": "004_whatsapp_configs"
        }
    except Exception as e:
        logger.error(f"Error applying migration: {e}")
        # Si la tabla ya existe, no es un error grave
        if "already exists" in str(e).lower():
            return {
                "status": "success", 
                "message": "La tabla ya existe, migración ya aplicada"
            }
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/migration-status")
async def check_migration_status(user: dict = Depends(get_current_user)):
    """Verificar si la migración de WhatsApp está aplicada"""
    try:
        db = get_supabase_client()
        
        # Intentar consultar la tabla
        result = db.table("whatsapp_configs").select("count", count="exact").limit(1).execute()
        
        return {
            "migration_applied": True,
            "table": "whatsapp_configs",
            "count": result.count if hasattr(result, 'count') else 0
        }
    except Exception as e:
        return {
            "migration_applied": False,
            "error": str(e)
        }
