# Vendly Backend

FastAPI + Supabase + Meta WhatsApp Cloud API. Desplegado en Render:
`https://vendly-backend-uuos.onrender.com`

## Documentación

| Documento | Para qué |
|---|---|
| [DOCUMENTO-SEGURIDAD.md](docs/DOCUMENTO-SEGURIDAD.md) | Qué protege cada capa y **qué no**. Léelo antes de quitar una protección |
| [DOCUMENTO-ARQUITECTURA.md](docs/DOCUMENTO-ARQUITECTURA.md) | Estructura y decisiones de diseño |
| [DOCUMENTO-FLUJOS.md](docs/DOCUMENTO-FLUJOS.md) | Recorrido de un mensaje, del webhook a la respuesta |
| [GUIA-DESPLIEGUE.md](docs/GUIA-DESPLIEGUE.md) | Desplegar y configurar el entorno |
| [CHECKLIST-CONFIGURACION.md](docs/CHECKLIST-CONFIGURACION.md) | Variables y servicios que hay que dejar listos |

Los documentos del repo padre son punteros a estas copias: se mantiene una sola,
en el repo que se despliega.

## Desarrollo

```bash
pip install -r requirements.txt
cp .env.example .env      # rellenar; sin WHATSAPP_TOKEN_ENCRYPTION_KEY no arranca
uvicorn main:app --reload
pytest
```
