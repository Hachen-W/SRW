import pika
import json
import os
import redis
import time
import csv
import atexit
import uuid
from dotenv import load_dotenv

# Импортируем классы моделей
from models.pytorch_detector import PyTorchDetector
from models.pyara_detector import PyAraDetector

# Глобальные настройки метрик
METRICS_BUFFER = []
BATCH_SIZE = 10
LOGGING_FILE = 'metrics_log.csv'


def flush_metrics():
    """Сброс накопленных метрик в файл"""
    if not METRICS_BUFFER:
        return
    with open(LOGGING_FILE, mode='a', newline='') as f:
        writer = csv.writer(f)
        writer.writerows(METRICS_BUFFER)
    METRICS_BUFFER.clear()


# Гарантируем сохранение остатков при штатном завершении воркера
atexit.register(flush_metrics)


def log_timing(request_id, func_name, audio_duration, exec_time):
    """Добавление записи в буфер метрик"""
    METRICS_BUFFER.append([request_id, func_name, audio_duration, exec_time])
    if len(METRICS_BUFFER) >= BATCH_SIZE:
        flush_metrics()


def save_result_to_redis(redis_client, request_id, result_payload):
    """Сохранение ответа в Redis и возврат времени выполнения"""
    start_time = time.perf_counter()
    redis_client.set(request_id, json.dumps(result_payload), ex=3600)
    return time.perf_counter() - start_time


def cleanup_temporary_file(file_path):
    """Удаление обработанного аудиофайла"""
    if os.path.exists(file_path):
        os.remove(file_path)


def process_message(ch, method, properties, body, active_model, redis_client):
    """Основной callback для обработки сообщений из очереди"""
    e2e_start_time = time.perf_counter()
    task_data = json.loads(body)
    file_path = task_data["file_path"]
    request_id = task_data.get("request_id", str(uuid.uuid4()))

    print(f"[*] Началась обработка файла: {file_path}")
    duration = 0.0

    try:
        # Вся магия происходит здесь — делегируем работу активной модели
        result = active_model.process(file_path, request_id, log_timing)
        duration = result["duration"]

        result_payload = {
            "status": "completed",
            "prediction": result["prediction"],
            "verdict": result["verdict"]
        }

    except ValueError as ve:
        # Обработка специфичных ошибок валидации
        if str(ve) == "audio_too_short":
            result_payload = {"status": "failed", "reason": "audio_too_short"}
        else:
            result_payload = {"status": "error", "reason": str(ve)}

    except Exception as e:
        print(f"[!] Ошибка при обработке: {e}")
        result_payload = {"status": "error", "reason": str(e)}

    finally:
        # 1. Сохраняем результат (каким бы он ни был) в Redis
        t_redis = save_result_to_redis(
            redis_client, request_id, result_payload
            )
        log_timing(request_id, 'save_result_to_redis', duration, t_redis)

        # 2. Подчищаем за собой и подтверждаем сообщение брокеру
        cleanup_temporary_file(file_path)
        ch.basic_ack(delivery_tag=method.delivery_tag)

        # 3. Логируем полное время обработки (End-to-End)
        e2e_total_time = time.perf_counter() - e2e_start_time
        log_timing(request_id, 'process_message_e2e', duration, e2e_total_time)

    print(f"[*] Закончилась обработка файла: {file_path}")


if __name__ == "__main__":
    # Загружаем переменные окружения
    load_dotenv()

    # Фабрика выбора модели: читаем из .env, по умолчанию используем pytorch
    model_type = os.getenv("MODEL_TYPE", "pytorch").lower()

    print(f"[*] Инициализация модели: {model_type}")
    if model_type == "pyara":
        detector = PyAraDetector()
    else:
        detector = PyTorchDetector()

    # Инициализация Redis
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_client = redis.Redis(
        host=redis_host, port=6379, db=0, decode_responses=True
    )

    # Инициализация RabbitMQ
    connection = pika.BlockingConnection(pika.ConnectionParameters(
        host='localhost')
    )
    channel = connection.channel()
    channel.queue_declare(queue='audio_processing_queue', durable=True)

    # Используем lambda для передачи зависимостей
    channel.basic_consume(
        queue='audio_processing_queue',
        on_message_callback=lambda ch, m, p, b: process_message(
            ch, m, p, b, detector, redis_client
            )
    )

    print(
        f"[*] Универсальный воркер ({model_type.upper()}) " +
        "успешно запущен. Ожидание аудиозаписей..."
        )
    channel.start_consuming()
