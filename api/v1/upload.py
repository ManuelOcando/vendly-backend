from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from api.deps import get_current_tenant
from db.supabase import get_supabase_client
from typing import List
import uuid
import mimetypes
import logging

router = APIRouter(prefix="/upload")

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/jpg"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_IMAGES_PER_PRODUCT = 5

logger = logging.getLogger(__name__)


@router.post("/images")
async def upload_images(
    files: List[UploadFile] = File(...),
    product_id: str = Form(...),
    tenant: dict = Depends(get_current_tenant)
):
    """
    Subir imágenes de producto a Supabase Storage.
    Máximo 5 imágenes por producto, 5MB cada una.
    """
    db = get_supabase_client()
    tenant_id = tenant["id"]
    
    logger.info(f"Upload request: {len(files)} files, product_id={product_id}, tenant={tenant_id}")
    
    uploaded_urls = []
    errors = []
    
    # Validar cantidad de archivos
    if len(files) > MAX_IMAGES_PER_PRODUCT:
        raise HTTPException(
            status_code=400, 
            detail=f"Máximo {MAX_IMAGES_PER_PRODUCT} imágenes permitidas"
        )
    
    for file in files:
        try:
            # Validar tipo de archivo
            content_type = file.content_type or mimetypes.guess_type(file.filename)[0]
            if content_type not in ALLOWED_TYPES:
                errors.append(f"{file.filename}: Tipo no permitido. Solo JPG, PNG, WebP")
                continue
            
            # Leer contenido y validar tamaño
            content = await file.read()
            if len(content) > MAX_FILE_SIZE:
                errors.append(f"{file.filename}: Archivo muy grande (máx 5MB)")
                continue
            
            # Generar nombre único
            ext = file.filename.split(".")[-1].lower() if "." in file.filename else "jpg"
            unique_name = f"{uuid.uuid4().hex}.{ext}"
            storage_path = f"products/{tenant_id}/{product_id}/{unique_name}"
            
            # Subir a Supabase Storage
            logger.info(f"Uploading to bucket 'vendly-uploads', path: {storage_path}")
            result = db.storage.from_("vendly-uploads").upload(
                storage_path,
                content,
                {"content-type": content_type}
            )
            
            logger.info(f"Upload result type: {type(result)}, value: {result}")
            
            if hasattr(result, 'error') and result.error:
                logger.error(f"Storage error for {file.filename}: {result.error}")
                errors.append(f"{file.filename}: Error de storage - {result.error}")
                continue
            
            # Obtener URL pública
            public_url = db.storage.from_("vendly-uploads").get_public_url(storage_path)
            uploaded_urls.append(public_url)
            
        except Exception as e:
            logger.exception(f"Error uploading {file.filename}")
            errors.append(f"{file.filename}: {str(e)}")
    
    return {
        "uploaded": len(uploaded_urls),
        "urls": uploaded_urls,
        "errors": errors,
        "product_id": product_id
    }


@router.delete("/images")
async def delete_image(
    image_url: str,
    tenant: dict = Depends(get_current_tenant)
):
    """Eliminar una imagen de producto del storage."""
    db = get_supabase_client()
    tenant_id = tenant["id"]
    
    try:
        # Extraer path de la URL
        # URL format: .../storage/v1/object/public/vendly-uploads/products/{tenant_id}/...
        path_parts = image_url.split("/vendly-uploads/")
        if len(path_parts) < 2:
            raise HTTPException(status_code=400, detail="URL inválida")
        
        storage_path = path_parts[1]
        
        # Verificar que pertenece al tenant
        if not storage_path.startswith(f"products/{tenant_id}/"):
            raise HTTPException(status_code=403, detail="No autorizado para eliminar esta imagen")
        
        # Eliminar de storage
        result = db.storage.from_("vendly-uploads").remove([storage_path])
        
        if hasattr(result, 'error') and result.error:
            raise HTTPException(status_code=500, detail=f"Error eliminando: {result.error}")
        
        return {"success": True, "message": "Imagen eliminada"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
