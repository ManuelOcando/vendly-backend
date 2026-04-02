import httpx
from config import get_settings


class RedisClient:
    """Cliente para Upstash Redis REST API"""
    
    def __init__(self):
        settings = get_settings()
        self.url = settings.UPSTASH_REDIS_URL
        self.token = settings.UPSTASH_REDIS_TOKEN
        self.headers = {
            "Authorization": f"Bearer {self.token}"
        }
    
    async def set(self, key: str, value: str, ex: int = None) -> bool:
        """Guardar un valor. ex = expiración en segundos."""
        cmd = ["SET", key, value]
        if ex:
            cmd.extend(["EX", str(ex)])
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.url,
                headers=self.headers,
                json=cmd
            )
            return response.status_code == 200
    
    async def get(self, key: str) -> str | None:
        """Obtener un valor."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.url,
                headers=self.headers,
                json=["GET", key]
            )
            data = response.json()
            return data.get("result")
    
    async def delete(self, key: str) -> bool:
        """Eliminar un valor."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.url,
                headers=self.headers,
                json=["DEL", key]
            )
            return response.status_code == 200
    
    async def exists(self, key: str) -> bool:
        """Verificar si existe una key."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.url,
                headers=self.headers,
                json=["EXISTS", key]
            )
            data = response.json()
            return data.get("result", 0) == 1


def get_redis_client() -> RedisClient:
    return RedisClient()