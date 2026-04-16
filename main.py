from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
import os
from config import get_settings
from api.v1.router import router as v1_router
from middleware.rate_limiter import limiter, rate_limit_exception_handler
from slowapi.errors import RateLimitExceeded
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

# Add rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)

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

# CORS - permitir frontend
# Lista de orígenes permitidos (filtrar vacíos)
origins = list(filter(None, [
    settings.FRONTEND_URL,
    "http://localhost:3000",
    "https://vendly-frontend.vercel.app",
    "https://vendly-storefront.vercel.app",
    "https://vendly-frontend.vercel.app",  # Duplicado intencional por si acaso
]))

# Eliminar duplicados manteniendo orden
seen = set()
origins = [x for x in origins if not (x in seen or seen.add(x))]

# En producción, si FRONTEND_URL no está configurado, agregar wildcard temporal
if not settings.DEBUG and len(origins) < 2:
    logger.warning("FRONTEND_URL not configured, adding temporary wildcard")
    origins.append("*")

# Agregar wildcard para desarrollo
if settings.DEBUG:
    origins.append("*")

logger.info(f"CORS configured with origins: {origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,  # 24 horas
)

# Ensure CORS headers are added to all responses including errors
@app.middleware("http")
async def cors_middleware(request, call_next):
    response = await call_next(request)
    origin = request.headers.get("origin")
    if origin in origins or "*" in origins:
        response.headers["Access-Control-Allow-Origin"] = origin if origin in origins else origins[0] if origins else "*"
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

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


@app.on_event("startup")
async def startup_event():
    logger.info(f"Application startup complete - {settings.APP_NAME}")
    if not settings.DEBUG:
        logger.info("Production mode enabled - All required environment variables validated")
    
    # Debug: List all registered routes
    logger.info("Registered routes:")
    for route in app.routes:
        if hasattr(route, 'methods') and hasattr(route, 'path'):
            logger.info(f"  {route.methods} {route.path}")