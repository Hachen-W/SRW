import pika
import json
import os
import redis
import time
import uuid
from dotenv import load_dotenv

# Импорты модулей
from models.pytorch_detector import PyTorchDetector
from models.pyara_detector import PyAraDetector
from utils.metrics import MetricsLogger


def connect_to_rabbitmq(host, attempts=15, pause=3):
    """Ждёт брокер: при старте контейнеров он может быть ещё не готов."""
    for attempt in range(1, attempts + 1):
        try:
            return pika.BlockingConnection(pika.ConnectionParameters(host=host))
        except pika.exceptions.AMQPConnectionError:
            print(f"[!] RabbitMQ недоступен ({attempt}/{attempts}), жду {pause} c")
            time.sleep(pause)
    raise RuntimeError(f"RabbitMQ на {host} так и не ответил")


class DetectorPool:
    """Держит модели по имени и создаёт их при первом обращении."""

    def __init__(self, default_name):
        self.default_name = default_name
        self.loaded = {}

    def get(self, name):
        name = (name or self.default_name).lower()
        if name not in ("pytorch", "pyara"):
            name = self.default_name
        if name not in self.loaded:
            print(f"[*] Инициализация модели: {name}")
            self.loaded[name] = (
                PyAraDetector() if name == "pyara" else PyTorchDetector()
            )
        return name, self.loaded[name]


def save_result_to_redis(redis_client, request_id, result_payload):
    start_time = time.perf_counter()
    redis_client.set(request_id, json.dumps(result_payload), ex=3600)
    return time.perf_counter() - start_time


def cleanup_temporary_file(file_path):
    if os.path.exists(file_path):
        os.remove(file_path)


def process_message(
        ch, method, properties, body, pool, redis_client, logger
        ):
    e2e_start_time = time.perf_counter()
    task_data = json.loads(body)
    file_path = task_data["file_path"]
    request_id = task_data.get("request_id", str(uuid.uuid4()))
    model_name, active_model = pool.get(task_data.get("model"))

    print(f"[*] Началась обработка файла: {file_path} ({model_name})")
    duration = 0.0

    try:
        # Передаем метод logger.log_timing внутрь модели как коллбэк
        result = active_model.process(file_path, request_id, logger.log_timing)
        duration = result["duration"]

        result_payload = {
            "status": "completed",
            "prediction": result["prediction"],
            "verdict": result["verdict"],
            "model": model_name
        }

    except ValueError as ve:
        if str(ve) == "audio_too_short":
            result_payload = {"status": "failed", "reason": "audio_too_short"}
        else:
            result_payload = {"status": "error", "reason": str(ve)}
    except Exception as e:
        print(f"[!] Ошибка при обработке: {e}")
        result_payload = {"status": "error", "reason": str(e)}

    finally:
        t_redis = save_result_to_redis(
            redis_client, request_id, result_payload
            )
        logger.log_timing(
            request_id, 'save_result_to_redis', duration, t_redis
            )

        cleanup_temporary_file(file_path)
        ch.basic_ack(delivery_tag=method.delivery_tag)

        e2e_total_time = time.perf_counter() - e2e_start_time
        logger.log_timing(
            request_id, 'process_message_e2e', duration, e2e_total_time
            )
    print(f"[*] Закончилась обработка файла: {file_path}")


if __name__ == "__main__":
    load_dotenv()

    model_type = os.getenv("MODEL_TYPE", "pytorch").lower()

    # Инициализируем логгер с именем конкретной модели
    logger = MetricsLogger(log_file=f"logs/{model_type}.csv", batch_size=10)

    # Модель выбирается в каждом запросе, MODEL_TYPE остаётся значением по умолчанию
    pool = DetectorPool(model_type)

    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_client = redis.Redis(
        host=redis_host, port=6379, db=0, decode_responses=True
        )

    rabbitmq_host = os.getenv("RABBITMQ_HOST", "localhost")
    connection = connect_to_rabbitmq(rabbitmq_host)
    channel = connection.channel()
    channel.queue_declare(queue='audio_processing_queue', durable=True)

    # Прокидываем logger в callback через lambda
    channel.basic_consume(
        queue='audio_processing_queue',
        on_message_callback=lambda ch, m, p, b: process_message(
            ch, m, p, b, pool, redis_client, logger
        )
    )

    print(f"[*] Универсальный воркер запущен. Модель по умолчанию: {model_type}")
    channel.start_consuming()
