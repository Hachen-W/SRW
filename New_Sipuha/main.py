from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse
import tempfile
import shutil
import uuid
import time
import json
import pika
import os
from dotenv import load_dotenv
import redis

from database.create_tables import create_tables
from routes import router_auth, router_audio
from contextlib import asynccontextmanager
from authx.exceptions import JWTDecodeError


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield


# Загружаем переменные из файла .env
load_dotenv()

# Получаем адрес из окружения. Если его нет, используем 'localhost'
redis_host = os.getenv("REDIS_HOST", "localhost") 
redis_client = redis.Redis(host=redis_host, port=6379, db=0, decode_responses=True)

app = FastAPI(lifespan=lifespan)
app.include_router(router_auth)
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {"wav", "mp3", "aac", "flac", "ogg"}


@app.get("/api/v1/result/{request_id}")
async def get_result(request_id: str):
    # 1. Проверяем наличие записи в Redis по ключу request_id
    raw_result = redis_client.get(request_id)

    # 2. Если воркер еще не успел записать результат
    if raw_result is None:
        return {"status": "processing"}

    # 3. Если результат готов, распаковываем JSON и отдаем его клиенту
    return json.loads(raw_result)


@app.post("/api/v1/detect", status_code=202)
async def detect_deepfake(file: UploadFile = File(...)):
    # 1. Быстрые проверки (размер и расширение)
    if file.size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large")

    ext = file.filename.split('.')[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Bad Request")

    # 2. Моментально сохраняем файл на диск, чтобы воркер мог его забрать
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as temp_file:
        shutil.copyfileobj(file.file, temp_file)
        file_path = temp_file.name

    # 3. Формируем пакет метаданных
    rabbitmq_host = os.getenv("RABBITMQ_HOST", "localhost")
    connection = pika.BlockingConnection(pika.ConnectionParameters(host=rabbitmq_host))
    channel = connection.channel()
    channel.queue_declare(queue='audio_processing_queue', durable=True)

    req_id = str(uuid.uuid4())
    message_data = {
        "request_id": req_id,
        "client_id": "ivr_system_01",
        "timestamp": time.time(),
        "file_path": file_path,  # Передаем путь воркеру
        "priority": "high"
    }

    # 4. Отправляем в RabbitMQ
    channel.basic_publish(
        exchange='',
        routing_key='audio_processing_queue',
        body=json.dumps(message_data)
    )
    connection.close()  # Шлюз отправил и сразу закрыл соединение

    # 5. Сразу же возвращаем ответ клиенту. Файл НЕ удаляем — его удалит воркер!
    return {"status": "accepted", "request_id": req_id}


@app.exception_handler(JWTDecodeError)
async def authx_jwt_decode_handler(request: Request, exc: JWTDecodeError):
    return JSONResponse(
        status_code=401,
        content={"detail": "Сессия истекла. Пожалуйста, войдите снова.", "error": str(exc)}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
