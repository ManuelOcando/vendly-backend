from fastapi import Depends, HTTPException, Header
from db.supabase import get_supabase_client


async def get_current_user(
    authorization: str = Header(None)
) -> dict:
    """
    Verifica el token JWT de Supabase y retorna el usuario.
    El frontend envía: Authorization: Bearer <token>
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token no proporcionado")

    token = authorization.replace("Bearer ", "")
    db = get_supabase_client()

    try:
        user_response = db.auth.get_user(token)
        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Token inválido")

        return {
            "id": user_response.user.id,
            "email": user_response.user.email,
            "metadata": user_response.user.user_metadata or {}
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Error de autenticación: {str(e)}")


async def get_current_tenant(
    current_user: dict = Depends(get_current_user)
) -> dict:
    """
    Obtiene el tenant del usuario autenticado.
    """
    db = get_supabase_client()

    response = db.table("tenants").select("*").eq(
        "owner_id", current_user["id"]
    ).execute()

    if not response.data or len(response.data) == 0:
        raise HTTPException(
            status_code=404,
            detail="No tienes un negocio configurado. Completa el registro."
        )

    return response.data[0]