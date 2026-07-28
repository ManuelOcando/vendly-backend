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

    async def _command(self, cmd: list) -> dict:
        """Ejecutar un comando y devolver la respuesta JSON de Upstash."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.url,
                headers=self.headers,
                json=cmd
            )
            return response.json()

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

    async def setex(self, key: str, seconds: int, value: str) -> bool:
        """Guardar un valor con TTL, con el orden de argumentos de SETEX."""
        return await self.set(key, value, ex=seconds)

    async def incrby(self, key: str, amount: int = 1) -> int:
        """Incrementar un contador. Devuelve el valor resultante."""
        data = await self._command(["INCRBY", key, str(amount)])
        return int(data.get("result") or 0)

    async def decrby(self, key: str, amount: int = 1) -> int:
        """Decrementar un contador. Devuelve el valor resultante."""
        data = await self._command(["DECRBY", key, str(amount)])
        return int(data.get("result") or 0)

    async def expire(self, key: str, seconds: int) -> bool:
        """Fijar TTL sobre una key existente."""
        data = await self._command(["EXPIRE", key, str(seconds)])
        return data.get("result", 0) == 1


def get_redis_client() -> RedisClient:
    return RedisClient()
