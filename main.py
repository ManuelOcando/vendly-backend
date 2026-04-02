from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import get_settings
from api.v1.router import router as v1_router

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc"
)

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
        "docs": "/docs",
        "health": "/api/v1/health"
    }