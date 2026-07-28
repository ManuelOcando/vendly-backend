import logging

import httpx

from config import get_settings

logger = logging.getLogger(__name__)


class RedisError(RuntimeError):
    """Upstash no pudo atender el comando.

    Existe para separar "la key no está" de "Redis no contestó". Antes las dos
    cosas devolvían None o False, así que un Redis caído se veía exactamente
    igual que un carrito expirado: el bot respondía "carrito expirado" y la API
    devolvía 404, sin un solo error en los logs. Así estuvo roto el flujo de
    carritos durante días sin que nadie lo notara.
    """


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
        """Ejecutar un comando y devolver la respuesta JSON de Upstash.

        Lanza RedisError si el comando no llegó, si Upstash respondió con un
        código distinto de 200, o si el payload trae un `error` (token
        inválido, comando mal formado). Cada caso queda logueado en ERROR.
        """
        name = cmd[0]

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.url,
                    headers=self.headers,
                    json=cmd
                )
        except httpx.HTTPError as e:
            # Incluye timeouts y fallos de DNS - el modo en que murió la
            # instancia anterior de Upstash.
            logger.error("Redis %s no pudo llegar a Upstash: %s", name, e, exc_info=True)
            raise RedisError(f"{name} no pudo llegar a Upstash: {e}") from e

        if response.status_code != 200:
            logger.error(
                "Redis %s devolvió HTTP %s: %s",
                name, response.status_code, response.text[:200]
            )
            raise RedisError(f"{name} devolvió HTTP {response.status_code}")

        data = response.json()
        if "error" in data:
            logger.error("Redis %s falló: %s", name, data["error"])
            raise RedisError(f"{name}: {data['error']}")

        return data

    async def set(self, key: str, value: str, ex: int = None) -> bool:
        """Guardar un valor. ex = expiración en segundos."""
        cmd = ["SET", key, value]
        if ex:
            cmd.extend(["EX", str(ex)])

        await self._command(cmd)
        return True

    async def get(self, key: str) -> str | None:
        """Obtener un valor. None significa que la key no existe."""
        data = await self._command(["GET", key])
        return data.get("result")

    async def delete(self, key: str) -> bool:
        """Eliminar un valor. True si la key existía."""
        data = await self._command(["DEL", key])
        return (data.get("result") or 0) > 0

    async def exists(self, key: str) -> bool:
        """Verificar si existe una key."""
        data = await self._command(["EXISTS", key])
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
