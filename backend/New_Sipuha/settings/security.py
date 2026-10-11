from authx import AuthX
from settings.config import AuthConfig

# Только проверка подписи токенов. Хеширование паролей осталось в сервисе
# аутентификации — своих пользователей здесь нет.
auth_config = AuthConfig()
security = AuthX(config=auth_config)
