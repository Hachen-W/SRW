"""Проверка токенов, выданных сервисом аутентификации.

Базы пользователей здесь нет: роль лежит прямо в токене, поэтому достаточно
проверить подпись общим секретом и прочитать claims. Сетевого обращения к
сервису аутентификации в рабочем режиме не происходит.
"""
import os
from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from settings.security import security

# Необязательная проверка выхода. Сервис аутентификации при logout кладёт в
# свой Redis метку logout:{user_id}. Если указать здесь тот же Redis, токены,
# выданные до выхода, перестанут приниматься. Без этого токен живёт до exp.
AUTH_REDIS_HOST = os.getenv("AUTH_REDIS_HOST", "")
AUTH_REDIS_PORT = int(os.getenv("AUTH_REDIS_PORT", "6379"))

auth_redis = None
if AUTH_REDIS_HOST:
    auth_redis = redis.Redis(
        host=AUTH_REDIS_HOST, port=AUTH_REDIS_PORT, db=0, decode_responses=True
    )


class TokenService:
    @staticmethod
    def get_token_from_request(request):
        token = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        return token

    @staticmethod
    def verify(token: str) -> dict:
        """Проверяет токен и возвращает сведения о сессии."""
        if not token:
            raise HTTPException(status_code=401, detail="No token provided")

        try:
            payload = security._decode_token(token)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        user_id = payload.sub
        role = payload.role

        if auth_redis is not None:
            TokenService.check_logout(user_id, payload.iat)

        return {
            "user_id": user_id,
            "role": role,
            "token_valid": True,
        }

    @staticmethod
    def check_logout(user_id: str, token_iat):
        """Отклоняет токены, выданные до последнего выхода пользователя."""
        try:
            logout_raw = auth_redis.get(f"logout:{user_id}")
        except redis.RedisError:
            return          # Redis недоступен — не роняем запрос из-за этого

        if not logout_raw:
            return

        logout_time = datetime.fromtimestamp(float(logout_raw), tz=timezone.utc)
        issued_at = datetime.fromtimestamp(token_iat, tz=timezone.utc)
        if issued_at < logout_time:
            raise HTTPException(
                status_code=401, detail="Token issued before last logout"
            )
