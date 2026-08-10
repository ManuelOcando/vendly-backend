from fastapi import APIRouter, Depends, Request, Header
from api.deps import get_current_user
from db.supabase import get_supabase_client
from db.redis import get_redis_client
from config import get_settings
from middleware.rate_limiter import limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
import logging
import time

logger = logging.getLogger(__name__)
router = APIRouter()


def _network_report(request: Request) -> dict:
    """
    Que direccion cree el servidor que tiene enfrente, y que dijeron los
    proxies. Existe para decidir como llavear el rate limiting.

    slowapi.get_remote_address devuelve request.client.host y nunca lee
    X-Forwarded-For. Quien puede reescribir request.client es el
    ProxyHeadersMiddleware de uvicorn, y solo si el par TCP esta en
    --forwarded-allow-ips, que por defecto es 127.0.0.1. Comparar los dos
    valores dice en cual de los dos mundos estamos:

      client_host == alguna entrada de x_forwarded_for
          -> uvicorn confia en el proxy y llavea por IP real de cliente.
      client_host es otra cosa (una IP interna)
          -> las cabeceras se ignoran y TODOS los clientes comparten cubo:
             cualquier limite por IP estrangula a los legitimos entre si.

    No expone nada: a quien llama le devuelve su propia direccion y las
    cabeceras que el mismo mando.
    """
    return {
        "rate_limit_key": get_remote_address(request),
        "client_host": request.client.host if request.client else None,
        "x_forwarded_for": request.headers.get("x-forwarded-for"),
        "x_real_ip": request.headers.get("x-real-ip"),
        "forwarded": request.headers.get("forwarded"),
    }


def _llm_config_report() -> dict:
    """
    Que proveedor y modelo estan configurados, y si hay clave.

    Son lecturas de configuracion y nada mas: ni red, ni construir el cliente.
    Construirlo cuesta 2-3 segundos medidos (GenerativeModel hace trabajo de
    red al instanciarse) y /health lo sondea Render sin parar, asi que eso vive
    en /health/llm junto con la generacion real.
    """
    settings = get_settings()

    if settings.LLM_PROVIDER == "openrouter":
        model, key = settings.OPENROUTER_MODEL, settings.OPENROUTER_API_KEY
    else:
        model, key = settings.GEMINI_MODEL, settings.GEMINI_API_KEY

    return {
        "enabled": settings.LLM_ENABLED,
        "provider": settings.LLM_PROVIDER,
        "model": model,
        # Solo present/missing, nunca el valor: distingue "sin configurar" de
        # "configurada y rechazada", que es todo lo que hace falta saber aqui.
        "api_key": "present" if key else "missing",
    }


@router.get("/health")
@limiter.limit("100/minute")
async def health_check(request: Request):
    """Verifica que el servidor está funcionando."""
    settings = get_settings()
    
    checks = {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": "development" if settings.DEBUG else "production",
        "supabase": "unknown",
        "redis": "unknown",
        "llm": _llm_config_report(),
        "network": _network_report(request),
    }

    # Verificar Supabase
    try:
        db = get_supabase_client()
        # Intentar una query simple
        db.table("tenants").select("id").limit(1).execute()
        checks["supabase"] = "connected"
    except Exception as e:
        checks["supabase"] = f"error: {str(e)}"
        logger.warning(f"Supabase health check failed: {e}")
    
    # Verificar Redis
    try:
        redis = get_redis_client()
        await redis.set("health_check", "ok", ex=10)
        result = await redis.get("health_check")
        checks["redis"] = "connected" if result == "ok" else "error"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"
        logger.warning(f"Redis health check failed: {e}")
    
    # Determinar status general. El LLM cuenta como degradacion, no como
    # caida: desde que LLMHandler cede en vez de disculparse, con el LLM roto
    # el bot sigue saludando, mostrando el catalogo y tomando pedidos por
    # nombre a traves de la cadena determinista.
    if "error" in checks["supabase"] or "error" in checks["redis"]:
        checks["status"] = "degraded"
    elif checks["llm"]["enabled"] and checks["llm"]["api_key"] == "missing":
        checks["status"] = "degraded"

    return checks


@router.get("/health/llm")
@limiter.limit("10/minute")
async def llm_health_check(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Sonda profunda del LLM: hace una generacion real y mide el viaje completo.

    Pide autenticacion, a diferencia de /health. Cada llamada gasta cuota de
    Gemini, y un endpoint anonimo que gasta dinero es un grifo abierto: a
    10/minuto por IP son mas de 14.000 generaciones al dia para quien
    encuentre la ruta. El monitoreo automatico debe pegarle a /health, que es
    gratis; esta es para un operador con sesion.

    Existe por un apagon concreto. Al rotar la clave de Gemini se perdio el
    acceso al modelo - Google retira modelos "para usuarios nuevos" y la clave
    nueva ya no alcanzaba a gemini-2.5-flash - y el unico sintoma visible fue
    que los clientes recibian una disculpa por WhatsApp. La clave era valida,
    el proveedor se construia sin quejarse, y hasta el endpoint que lista
    modelos devolvia 200 con ese modelo dentro. Solo generar de verdad lo
    delata, y este endpoint devuelve el mensaje de error tal cual lo manda el
    proveedor, que es donde se lee el 404.

    Limitado a 10/minuto porque cada llamada gasta cuota.
    """
    settings = get_settings()
    report = _llm_config_report()

    if not settings.LLM_ENABLED:
        return {"status": "disabled", **report}

    # Construir el cliente es la primera cosa que puede fallar, y sola ya
    # distingue "mal configurado" de "configurado pero el modelo rechaza".
    try:
        from services.llm.factory import get_llm_provider

        provider = get_llm_provider()
    except Exception as e:
        return {
            "status": "error",
            "stage": "client",
            "error": f"{type(e).__name__}: {e}",
            **report,
        }

    if not provider:
        return {"status": "error", "stage": "client", "error": "provider not created", **report}

    started = time.monotonic()

    try:
        response = await provider.generate_response(
            messages=[
                {"role": "system", "content": 'Responde solo con {"ok": true} en JSON.'},
                {"role": "user", "content": "ping"},
            ],
            temperature=0,
            # Holgado a proposito. Con 32 la sonda se autoinfligia un
            # finish_reason=MAX_TOKENS: los modelos que razonan gastan
            # presupuesto antes de emitir el primer caracter, y el fallo
            # parecia del modelo cuando lo causaba la sonda.
            max_tokens=512,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        return {
            "status": "error",
            "stage": "generate",
            "error": f"{type(e).__name__}: {e}",
            "latency_ms": int((time.monotonic() - started) * 1000),
            **report,
        }

    latency_ms = int((time.monotonic() - started) * 1000)

    # generate_response se traga sus errores: devuelve None, o un relleno con
    # forma de respuesta valida marcado con llm_error. Sin estas dos ramas la
    # sonda contesta "ok" ante el fallo exacto que la motivo - comprobado.
    if not isinstance(response, dict) or not response:
        return {
            "status": "error",
            "stage": "generate",
            "error": "el proveedor devolvio None o un tipo no esperado",
            "latency_ms": latency_ms,
            **report,
        }

    if response.get("llm_error"):
        return {
            "status": "error",
            "stage": "parse",
            "error": "el proveedor no pudo parsear su propia salida; ver sus logs",
            "latency_ms": latency_ms,
            **report,
        }

    return {"status": "ok", "latency_ms": latency_ms, **report}


@router.get("/debug-auth")
@limiter.limit("100/minute")
async def debug_auth(request: Request, authorization: str = Header(None)):
    """Debug endpoint to check authentication and tenant status."""
    logger.info(f"Debug auth called with authorization: {authorization[:20] if authorization else 'None'}...")
    
    result = {
        "has_auth_header": authorization is not None,
        "auth_header_format": False,
        "user_valid": False,
        "tenant_exists": False,
        "user_id": None,
        "tenant_id": None,
        "error": None
    }
    
    # Check authorization format
    if authorization and authorization.startswith("Bearer "):
        result["auth_header_format"] = True
        token = authorization.replace("Bearer ", "")
        
        try:
            # Check user
            db = get_supabase_client()
            user_response = db.auth.get_user(token)
            if user_response and user_response.user:
                result["user_valid"] = True
                result["user_id"] = user_response.user.id
                logger.info(f"User valid: {user_response.user.id}")
                
                # Check tenant
                tenant_response = db.table("tenants").select("*").eq(
                    "owner_id", user_response.user.id
                ).execute()
                
                if tenant_response.data and len(tenant_response.data) > 0:
                    result["tenant_exists"] = True
                    result["tenant_id"] = tenant_response.data[0]["id"]
                    logger.info(f"Tenant found: {tenant_response.data[0]['id']}")
                else:
                    result["error"] = "No tenant found for user"
                    logger.warning(f"No tenant for user {user_response.user.id}")
            else:
                result["error"] = "Invalid token"
                logger.warning("Invalid token")
                
        except Exception as e:
            result["error"] = f"Auth error: {str(e)}"
            logger.error(f"Auth error: {e}")
    else:
        result["error"] = "Missing or invalid authorization header"
        logger.warning("Missing or invalid auth header")
    
    return result