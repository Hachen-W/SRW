import os
import json
import time
import uuid
import shutil
import tempfile
import pika
import redis
import asyncio
from fastapi import APIRouter, Depends, UploadFile, \
    File, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from database.create_tables import get_db
from services.auth_service import AuthService
from .auth import rate_limit_dependency, security_bearer

router_audio = APIRouter(prefix="/audio", tags=["Audio Processing"])

# Инициализация Redis
redis_host = os.getenv("REDIS_HOST", "localhost")
redis_client_raw = redis.Redis(host=redis_host, port=6379, db=0, decode_responses=False)
redis_client_json = redis.Redis(host=redis_host, port=6379, db=0, decode_responses=True)

# Лимит на размер загружаемого файла. Меняется переменной окружения,
# пересобирать образ не нужно.
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", "500")) * 1024 * 1024
ALLOWED_EXTENSIONS = {"wav", "mp3", "aac", "flac", "ogg"}
ALLOWED_MODELS = {"pytorch", "pyara"}


def get_current_verified_session(
        request: Request, db: Session = Depends(get_db)
        ) -> dict:
    token = AuthService.get_token_from_request(request)
    return AuthService.protected_route(token, db)


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


@router_audio.websocket("/stream")
async def websocket_audio_stream(websocket: WebSocket, db: Session = Depends(get_db)):
    await websocket.accept()
    
    # Валидация токена (из query параметров или заголовка)
    token = websocket.query_params.get("token") or websocket.headers.get("authorization")
    if token and token.startswith("Bearer "):
        token = token.split(" ")[1]
    
    try:
        session_data = AuthService.protected_route(token, db)
        if session_data.get("role") not in ["SERVICE", "ADMIN"]:
            await websocket.close(code=4003, reason="Forbidden")
            return
    except Exception:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    # Модель выбирает клиент: ?model=pytorch или ?model=pyara
    model = websocket.query_params.get("model", "pytorch")
    if model not in ALLOWED_MODELS:
        await websocket.close(code=4000, reason="Unknown model")
        return

    session_id = str(uuid.uuid4())
    audio_channel = f"stream:audio:{session_id}"
    result_channel = f"stream:result:{session_id}"
    
    # Подписываемся на канал результатов от воркера
    pubsub = redis_client_json.pubsub()
    pubsub.subscribe(result_channel)
    
    async def listen_to_worker():
        """Асинхронная задача для чтения ответов из Redis от нашего ML-воркера"""
        try:
            while True:
                # Проверяем наличие сообщений от воркера
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.01)
                if message and message['type'] == 'message':
                    data = json.loads(message['data'])
                    await websocket.send_json(data)
                    
                    # Если воркер прислал команду на уничтожение сессии - прерываем цикл
                    if data.get("status") == "terminated":
                        await websocket.close(code=4003)
                        break
                await asyncio.sleep(0.01)
        except Exception as e:
            print(f"Ошибка отправки ответа клиенту: {e}")

    # Запускаем фоновое слушание ответов воркера
    listen_task = asyncio.create_task(listen_to_worker())

    # Сообщаем воркеру, какой моделью считать эту сессию.
    # Публикуем тем же соединением, что и звук: порядок сообщений гарантируется
    # только внутри одного соединения, иначе чанк может обогнать INIT.
    redis_client_raw.publish(
        audio_channel, json.dumps({"control": "INIT", "model": model}).encode()
        )

    try:
        while True:
            # Принимаем бинарный чанк аудио от IVR-системы
            chunk_bytes = await websocket.receive_bytes()
            
            # Пересылаем чанк воркеру в соседний терминал через RAM
            redis_client_raw.publish(audio_channel, chunk_bytes)

    except WebSocketDisconnect:
        print(f"[*] IVR разорвал соединение для сессии: {session_id}")
    finally:
        # Чистим ресурсы
        listen_task.cancel()
        pubsub.unsubscribe(result_channel)
        redis_client_raw.publish(
            audio_channel, json.dumps({"control": "EOF"}).encode()
            )


@router_audio.post("/detect", status_code=202, dependencies=[
    Depends(rate_limit_dependency),
    Depends(AudioAccessChecker(["SERVICE", "ADMIN"])),
    Depends(security_bearer)
    ])
async def detect_deepfake(
        file: UploadFile = File(...),
        model: str = Form("pytorch"),
        current_session: dict = Depends(get_current_verified_session)
        ):
    if model not in ALLOWED_MODELS:
        raise HTTPException(status_code=400, detail="Unknown model")

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
        "model": model,
        "priority": "high"
        }

    channel.basic_publish(
        exchange='',
        routing_key='audio_processing_queue',
        body=json.dumps(message_data)
    )
    connection.close()

    return {"status": "accepted", "request_id": req_id}


@router_audio.get("/result/{request_id}", dependencies=[
    Depends(rate_limit_dependency),
    Depends(security_bearer)
    ])
async def get_result(
        request_id: str,
        current_session: dict = Depends(get_current_verified_session)
        ):
    raw_result = redis_client_json.get(request_id)

    if raw_result is None:
        return {"status": "processing"}

    return json.loads(raw_result)
