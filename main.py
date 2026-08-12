from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
import asyncio
import os
from config import get_settings
from api.v1.router import router as v1_router
from db.schema_check import run_schema_check
from middleware.rate_limiter import limiter, rate_limit_exception_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize settings (will validate required env vars)
try:
    settings = get_settings()
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Debug mode: {settings.DEBUG}")
except ValueError as e:
    logger.error(f"Configuration error: {e}")
    raise

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None
)

# Add rate limiting. El middleware aplica DEFAULT_LIMITS a *toda* ruta; sin el,
# slowapi solo cuenta las decoradas una por una, que es como 22 rutas publicas
# se quedaron sin limite y como se quedaria sin limite la proxima que se añada.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)
app.add_middleware(SlowAPIMiddleware)

# Routes for legal pages (required for Meta approval)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.get("/privacy-policy", response_class=HTMLResponse, include_in_schema=False)
async def privacy_policy():
    """Privacy Policy page - Required for Meta/WhatsApp Business API approval"""
    privacy_file = os.path.join(BASE_DIR, "static", "privacy-policy.html")
    if os.path.exists(privacy_file):
        with open(privacy_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Privacy Policy - Coming Soon</h1>", status_code=503)

@app.get("/terms-of-service", response_class=HTMLResponse, include_in_schema=False)
async def terms_of_service():
    """Terms of Service page - Required for Meta/WhatsApp Business API approval"""
    terms_file = os.path.join(BASE_DIR, "static", "terms-of-service.html")
    if os.path.exists(terms_file):
        with open(terms_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Terms of Service - Coming Soon</h1>", status_code=503)

@app.get("/legal", response_class=HTMLResponse, include_in_schema=False)
async def legal_redirect():
    """Legal information page with links"""
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html>
    <head><title>Legal - Vendly</title></head>
    <body>
        <h1>Información Legal</h1>
        <ul>
            <li><a href="/privacy-policy">Política de Privacidad</a></li>
            <li><a href="/terms-of-service">Términos de Servicio</a></li>
        </ul>
    </body>
    </html>
    """)

# Security headers middleware
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    if not settings.DEBUG:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# CORS. Nunca "*", en ningun modo. Esta politica la aplica el navegador, no el
# servidor: un comodin no abre la API a curl (que nunca la miro), sino que
# permite que el JavaScript de cualquier web lea nuestras respuestas en el
# navegador del usuario. Y con credenciales activas Starlette refleja el origen
# de quien llama, asi que "*" no es el comodin anonimo que aparenta.
#
# Habia dos ramas que lo añadian. La de produccion pedia len(origins) < 2 y
# nunca se cumplia, porque la lista de abajo siempre trae tres literales: era
# codigo muerto aparentando proteccion. La de DEBUG si se cumplia.
ALLOWED_ORIGINS = (
    "http://localhost:3000",
    "https://vendly-frontend.vercel.app",
    "https://vendly-storefront.vercel.app",
)

origins = list(dict.fromkeys(filter(None, [settings.FRONTEND_URL, *ALLOWED_ORIGINS])))

logger.info(f"CORS configured with origins: {origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    # El backend no fija ni lee cookies en ningun punto: la sesion viaja en
    # Authorization: Bearer, que el navegador no adjunta por su cuenta. Con las
    # credenciales apagadas, un origen ajeno no puede aprovechar la sesion de
    # nadie aunque la lista de arriba se equivoque algun dia.
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,  # 24 horas
)

# Rutas
app.include_router(v1_router)


@app.get("/")
async def root():
    return {
        "message": "Bienvenido a Vendly API",
        "docs": "/docs" if settings.DEBUG else "Documentation disabled in production",
        "health": "/api/v1/health",
        "version": settings.APP_VERSION
    }


_schema_check_task = None


def _log_schema_check_completion(task):
    """Surface a schema check that died instead of letting it disappear."""
    if task.cancelled():
        logger.warning("Schema check was cancelled before it finished")
        return
    error = task.exception()
    if error is not None:
        logger.error("Schema check task failed: %s", error, exc_info=error)


@app.on_event("startup")
async def startup_event():
    logger.info(f"Application startup complete - {settings.APP_NAME}")
    if not settings.DEBUG:
        logger.info("Production mode enabled - All required environment variables validated")

    # Report any drift between the database and what the code expects. Fired as
    # a task, not awaited: it is one request per table and must not delay
    # readiness. It never raises and never blocks startup - drift should be loud
    # in the boot log, not a reason to refuse to serve.
    #
    # The reference is kept deliberately. asyncio holds only a weak reference to
    # a running task, so a bare create_task() can be garbage collected before it
    # finishes - which is exactly what happened the first time this was wired up:
    # the check silently never ran. The callback is here for the same reason, so
    # a failure inside the task cannot vanish either.
    global _schema_check_task
    _schema_check_task = asyncio.create_task(run_schema_check())
    _schema_check_task.add_done_callback(_log_schema_check_completion)


    # Debug: List all registered routes
    logger.info("Registered routes:")
    for route in app.routes:
        if hasattr(route, 'methods') and hasattr(route, 'path'):
            logger.info(f"  {route.methods} {route.path}")