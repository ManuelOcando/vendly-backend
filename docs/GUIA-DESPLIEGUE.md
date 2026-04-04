# VENDLY - GUÍA DE DESPLIEGUE

## Resumen de Plataformas

| Componente | Plataforma | URL Temporal |
|------------|------------|--------------|
| Frontend (Next.js) | Vercel | `https://vendly-frontend.vercel.app` |
| Backend (FastAPI) | Render | `https://vendly-api.onrender.com` |
| Base de Datos | Supabase | `https://slspihwznliibdecdtkj.supabase.co` |
| Redis | Upstash | Configurado en variables de entorno |

---

## PASO 1: Desplegar Backend en Render

### 1.1 Preparar el Backend

**Archivo `render.yaml` ya existe:**
```yaml
services:
  - type: web
    name: vendly-api
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn main:app --host 0.0.0.0 --port 8000
    envVars:
      - key: PYTHON_VERSION
        value: 3.11.0
```

**Verificar `requirements.txt`:**
```
fastapi==0.115.0
uvicorn[standard]==0.32.0
python-dotenv==1.0.1
supabase==2.9.0
httpx==0.27.2
pydantic-settings==2.6.1
pydantic==2.9.2
python-multipart==0.0.17
redis==5.2.0
```

### 1.2 Pasos en Render.com

1. **Ir a**: https://dashboard.render.com/
2. **Click**: "New +" → "Web Service"
3. **Conectar**: Tu repositorio de GitHub/GitLab
4. **Configurar**:
   - **Name**: `vendly-api`
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port 8000`
   - **Plan**: Free

5. **Variables de Entorno** (en Render Dashboard → Environment):
   ```
   SUPABASE_URL=https://slspihwznliibdecdtkj.supabase.co
   SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
   SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
   UPSTASH_REDIS_URL=https://your-url.upstash.io
   UPSTASH_REDIS_TOKEN=your-token
   EVOLUTION_API_URL=http://localhost:8080
   EVOLUTION_API_KEY=your-key
   FRONTEND_URL=https://vendly-frontend.vercel.app
   ```

6. **Click**: "Create Web Service"

### 1.3 Verificar Despliegue

- Esperar a que el build complete (2-3 minutos)
- URL será: `https://vendly-api.onrender.com`
- Probar: `https://vendly-api.onrender.com/api/v1/health`

---

## PASO 2: Desplegar Frontend en Vercel

### 2.1 Preparar el Frontend

**Verificar `next.config.ts`:**
```typescript
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'standalone',
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  },
};

export default nextConfig;
```

**Verificar `package.json`:**
```json
{
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint"
  }
}
```

### 2.2 Pasos en Vercel.com

1. **Ir a**: https://vercel.com/new
2. **Importar**: Tu repositorio de GitHub
3. **Configurar Proyecto**:
   - **Framework Preset**: Next.js
   - **Root Directory**: `vendly-frontend`
   - **Build Command**: `npm run build`
   - **Output Directory**: `.next`

4. **Variables de Entorno**:
   ```
   NEXT_PUBLIC_API_URL=https://vendly-api.onrender.com
   NEXT_PUBLIC_SUPABASE_URL=https://slspihwznliibdecdtkj.supabase.co
   NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
   ```

5. **Click**: "Deploy"

### 2.3 Verificar Despliegue

- Esperar a que el build complete (1-2 minutos)
- URL será: `https://vendly-frontend.vercel.app`
- Probar: Abrir la URL en navegador

---

## PASO 3: Configurar CORS en Backend

Una vez desplegado, actualizar `FRONTEND_URL` en Render:

```
FRONTEND_URL=https://vendly-frontend.vercel.app
```

Esto permite que el backend acepte peticiones del frontend desplegado.

---

## PASO 4: Configurar Webhook de WhatsApp

### 4.1 Evolution API

Si estás usando Evolution API propia:

1. Configurar webhook en Evolution API apuntando a:
   ```
   https://vendly-api.onrender.com/api/v1/whatsapp/webhook
   ```

2. Verificar que la instancia está conectada

### 4.2 Alternativa: Usar ngrok para testing

Si no tienes Evolution API desplegada:

```bash
# Instalar ngrok
# En terminal separada con backend local:
ngrok http 8000

# Usar la URL de ngrok como webhook temporal
# Ejemplo: https://abc123.ngrok.io/api/v1/whatsapp/webhook
```

---

## PASO 5: URLs Finales

Después del despliegue, tendrás:

| Servicio | URL Local | URL Producción |
|----------|-----------|----------------|
| Frontend | http://localhost:3000 | https://vendly-frontend.vercel.app |
| Backend API | http://localhost:8000 | https://vendly-api.onrender.com |
| API Docs | http://localhost:8000/docs | https://vendly-api.onrender.com/docs |
| Health | http://localhost:8000/api/v1/health | https://vendly-api.onrender.com/api/v1/health |

---

## COMANDOS RÁPIDOS

### Desplegar Frontend (si tienes Vercel CLI)
```bash
cd vendly-frontend
vercel --prod
```

### Desplegar Backend (Git push)
```bash
git add .
git commit -m "Ready for deployment"
git push origin main

# Render se actualiza automáticamente
```

---

## CHECKLIST POST-DESPLIEGUE

- [ ] Backend responde en URL de producción
- [ ] Frontend carga sin errores
- [ ] Login funciona (Supabase Auth)
- [ ] Registro de vendedor funciona
- [ ] Crear producto funciona
- [ ] Storefront público carga
- [ ] Carrito funciona
- [ ] WhatsApp webhook recibe mensajes (si aplica)

---

## SOLUCIÓN DE PROBLEMAS

### Build falla en Vercel
```bash
# Verificar build local primero
cd vendly-frontend
npm run build

# Si hay errores de TypeScript, corregirlos
```

### Build falla en Render
```bash
# Verificar que main.py está en root
cd vendly-backend
ls main.py

# Verificar que uvicorn está en requirements.txt
grep uvicorn requirements.txt
```

### CORS Error
```python
# En main.py, asegurar que FRONTEND_URL está en allow_origins
allow_origins=[
    "https://vendly-frontend.vercel.app",  # URL de producción
    "http://localhost:3000",               # Desarrollo
]
```

---

**Guía creada**: Abril 2025
**Proyecto**: Vendly MVP
