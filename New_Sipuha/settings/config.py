from pydantic_settings import BaseSettings, SettingsConfigDict  # <-- Добавили SettingsConfigDict
from authx import AuthXConfig               #for authx config
from datetime import timedelta


class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRES: timedelta = timedelta(minutes=2)     #2 minutes for access token
    JWT_REFRESH_TOKEN_EXPIRES: timedelta = timedelta(days=28)      #28 days for refresh token (keep in HTTP-only cookie)

    #Cookie settings
    JWT_ACCESS_COOKIE_NAME: str = "access_token"
    JWT_REFRESH_COOKIE_NAME: str = "refresh_token"
    JWT_TOKEN_LOCATION: list = ["headers", "cookies"]

    JWT_COOKIE_HTTPONLY: bool = True      #protect for XSS (block access from JS to cookies)
    #JWT_COOKIE_SECURE: bool = True       #https is needed (cookie only with https)
    JWT_COOKIE_SAMESITE: str = "lax"      #protect for CSRF (block post requests from other site)
    JWT_COOKIE_CSRF_PROTECT: bool = True  #more protect

    # --- ОБНОВЛЕНО ПОД PYDANTIC V2 ---
    model_config = SettingsConfigDict(
        env_file=".env",            # Указываем файл окружения
        env_file_encoding="utf-8",
        extra="ignore"              # Игнорируем переменные Redis/RabbitMQ, которых нет в этом классе
    )


settings = Settings()


class AuthConfig(AuthXConfig):
    JWT_SECRET_KEY: str = settings.JWT_SECRET_KEY
    JWT_ALGORITHM: str = settings.JWT_ALGORITHM
    JWT_ACCESS_TOKEN_EXPIRES: timedelta = settings.JWT_ACCESS_TOKEN_EXPIRES
    JWT_REFRESH_TOKEN_EXPIRES: timedelta = settings.JWT_REFRESH_TOKEN_EXPIRES
    JWT_ACCESS_COOKIE_NAME: str = settings.JWT_ACCESS_COOKIE_NAME
    JWT_REFRESH_COOKIE_NAME: str = settings.JWT_REFRESH_COOKIE_NAME
    JWT_TOKEN_LOCATION: list = settings.JWT_TOKEN_LOCATION
