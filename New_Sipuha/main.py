from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from database.create_tables import create_tables
from authx.exceptions import JWTDecodeError, AuthXException

from routes import router_auth, router_audio


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Автоматически создаем таблицы в БД при старте приложения
    create_tables()
    yield

# Загружаем переменные окружения из файла .env
load_dotenv()

app = FastAPI(lifespan=lifespan)

# Подключаем изолированные роутеры
app.include_router(router_auth)
app.include_router(router_audio)


@app.exception_handler(JWTDecodeError)
async def authx_jwt_decode_handler(request: Request, exc: JWTDecodeError):
    return JSONResponse(
        status_code=401,
        content={
            "detail": "Сессия истекла или токен поврежден. Пожалуйста, войдите снова.",
            "error": str(exc)
        }
    )


@app.exception_handler(AuthXException)
async def authx_exception_handler(request: Request, exc: AuthXException):
    # Этот обработчик спасает от 500-й ошибки, если токен забыли передать.
    # Теперь клиенту вернется цивилизованный статус 401 Unauthorized.
    return JSONResponse(
        status_code=401,
        content={
            "detail": "Ошибка аутентификации", 
            "reason": str(exc)
        }
    )


if __name__ == "__main__":
    import uvicorn
    # Запуск сервера
    uvicorn.run(app, host="0.0.0.0", port=8000)
