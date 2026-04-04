from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_URL,
        "http://localhost:3000",
        "https://*.vendly.app",
        "https://*.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.on_event("startup")
async def startup_event():
    logger.info(f"Application startup complete - {settings.APP_NAME}")
    if not settings.DEBUG:
        logger.info("Production mode enabled - All required environment variables validated")