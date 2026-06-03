import os
import json
import time
import uuid
import shutil
import tempfile
import pika
import redis
from fastapi import APIRouter, Depends, UploadFile, \
    File, HTTPException, Request
from sqlalchemy.orm import Session

from database.create_tables import get_db
from services.auth_service import AuthService
from .auth import rate_limit_dependency, security_bearer

router_audio = APIRouter(prefix="/audio", tags=["Audio Processing"])

# Инициализация Redis
redis_host = os.getenv("REDIS_HOST", "localhost")
redis_client = redis.Redis(
    host=redis_host, port=6379, db=0, decode_responses=True
    )

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {"wav", "mp3", "aac", "flac", "ogg"}


def get_current_verified_session(
        request: Request, db: Session = Depends(get_db)
        ) -> dict:
    token = AuthService.get_token_from_request(request)
    return AuthService.protected_route(token, db)


# Модифицированный класс для проверки ролей
class AudioAccessChecker:
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(
            self, session_data: dict = Depends(get_current_verified_session)
            ):
        if session_data.get("role") not in self.allowed_roles:
            raise HTTPException(
                status_code=403, detail="Not enough permissions"
                )
        return session_data


# Отправка аудио на детекцию (Доступен любому валидному пользователю)
@router_audio.post("/detect", status_code=202, dependencies=[
    Depends(rate_limit_dependency),
    Depends(AudioAccessChecker(["SERVICE", "ADMIN"])),
    Depends(security_bearer)
    ])
async def detect_deepfake(
        file: UploadFile = File(...),
        current_session: dict = Depends(get_current_verified_session)
        ):
    if file.size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large")

    ext = file.filename.split('.')[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Bad Request")

    with tempfile.NamedTemporaryFile(
            delete=False, suffix=f".{ext}"
            ) as temp_file:
        shutil.copyfileobj(file.file, temp_file)
        file_path = temp_file.name

    rabbitmq_host = os.getenv("RABBITMQ_HOST", "localhost")
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host=rabbitmq_host)
        )
    channel = connection.channel()
    channel.queue_declare(queue='audio_processing_queue', durable=True)

    req_id = str(uuid.uuid4())
    message_data = {
        "request_id": req_id,
        "client_id": "ivr_system_01",
        "timestamp": time.time(),
        "file_path": file_path,
        "priority": "high"
        }

    channel.basic_publish(
        exchange='',
        routing_key='audio_processing_queue',
        body=json.dumps(message_data)
    )
    connection.close()

    return {"status": "accepted", "request_id": req_id}


# 3. Получение результата (Доступен любому валидному пользователю)
@router_audio.get("/result/{request_id}", dependencies=[
    Depends(rate_limit_dependency),
    Depends(security_bearer)
    ])
async def get_result(
        request_id: str,
        current_session: dict = Depends(get_current_verified_session)
        ):
    raw_result = redis_client.get(request_id)

    if raw_result is None:
        return {"status": "processing"}

    return json.loads(raw_result)
