import pika
import json
import librosa
import os
import redis
import time
import csv
import atexit
import uuid
from dotenv import load_dotenv

import pyara.main


# Глобальный буфер для накопления метрик
METRICS_BUFFER = []
BATCH_SIZE = 10


def flush_metrics():
    """Сброс накопленных метрик в файл"""
    if not METRICS_BUFFER:
        return
    with open('benchmark_log.csv', mode='a', newline='') as f:
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


def save_result_to_redis(request_id, result_payload):
    start_time = time.perf_counter()
    redis_client.set(request_id, json.dumps(result_payload), ex=3600)
    return time.perf_counter() - start_time


def cleanup_temporary_file(file_path):
    if os.path.exists(file_path):
        os.remove(file_path)


def process_message(ch, method, properties, body):
    e2e_start_time = time.perf_counter()
    task_data = json.loads(body)
    file_path = task_data["file_path"]
    request_id = task_data.get("request_id", str(uuid.uuid4()))

    print(f"[*] Началась обработка файла: {file_path}")
    duration = 0.0

    try:
        # Получаем длительность для метрик без полной загрузки в память
        start_time = time.perf_counter()
        duration = librosa.get_duration(path=file_path)
        t_duration = time.perf_counter() - start_time
        log_timing(request_id, 'get_audio_duration', duration, t_duration)

        if duration < 1.0:
            result_payload = {"status": "failed", "reason": "audio_too_short"}
            t_redis = save_result_to_redis(request_id, result_payload)
            log_timing(request_id, 'save_result_to_redis', duration, t_redis)
            return

        # Инференс через PyAra
        start_time = time.perf_counter()
        decision = pyara.main.predict_audio(str(file_path))
        t_inf = time.perf_counter() - start_time
        log_timing(request_id, 'run_pyara_inference', duration, t_inf)

        # 1 - Сгенерировано нейросетью, 0 - оригинальная дорожка
        verdict = "spoof" if decision == 1 else "bonafide"
        
        result_payload = {
            "status": "completed",
            "prediction": decision,
            "verdict": verdict
        }

        t_redis = save_result_to_redis(request_id, result_payload)
        log_timing(request_id, 'save_result_to_redis', duration, t_redis)

    except Exception as e:
        print(f"[!] Ошибка при обработке: {e}")
        error_payload = {
            "status": "error",
            "reason": str(e)
        }
        save_result_to_redis(request_id, error_payload)

    finally:
        cleanup_temporary_file(file_path)
        ch.basic_ack(delivery_tag=method.delivery_tag)

        # Логируем полное время обработки (End-to-End)
        e2e_total_time = time.perf_counter() - e2e_start_time
        log_timing(request_id, 'process_message_e2e', duration, e2e_total_time)


if __name__ == "__main__":
    load_dotenv()

    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_client = redis.Redis(
        host=redis_host, port=6379, db=0, decode_responses=True
    )

    connection = pika.BlockingConnection(pika.ConnectionParameters(
        host='localhost')
    )
    channel = connection.channel()
    channel.queue_declare(queue='audio_processing_queue', durable=True)
    channel.basic_consume(
        queue='audio_processing_queue', on_message_callback=process_message
    )

    print("[*] PyAra воркер успешно запущен. Ожидание аудиозаписей...")
    channel.start_consuming()
