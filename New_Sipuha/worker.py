import pika
import json
import librosa
import os
from scipy.signal import welch, wiener
import numpy as np
import torch
import torch.nn as nn
import os
from dotenv import load_dotenv
import redis


class DummyDeepfakeDetector(nn.Module):
    def __init__(self):
        super().__init__()
        # Здесь могли бы быть реальные слои (сверточные, линейные),
        # но для заглушки они нам пока не нужны.

    def forward(self, audio_tensor):
        return torch.rand(1).item()


# Загружаем переменные из файла .env
load_dotenv()

# Инициализация модели
model = DummyDeepfakeDetector()

# Получаем адрес из окружения. Если его нет, используем 'localhost'
redis_host = os.getenv("REDIS_HOST", "localhost") 
redis_client = redis.Redis(host=redis_host, port=6379, db=0, decode_responses=True)


# Сюда переезжают наши вычислительные функции
def calculate_snr(audio):
    frequencies, psd = welch(audio, fs=16000, nperseg=320)
    speech_mask = (frequencies >= 300) & (frequencies <= 4000)
    power_signal = psd[speech_mask].sum()
    power_noise = psd[~speech_mask].sum()
    if power_noise == 0:
        return float('inf')
    return 10 * np.log10(power_signal / power_noise)


def apply_wiener_filter(audio):
    return wiener(audio)


# Эта функция вызывается автоматически, когда в RabbitMQ приходит задача
def process_message(ch, method, properties, body):
    task_data = json.loads(body)
    file_path = task_data["file_path"]

    print(f"[*] Началась обработка файла: {file_path}")

    try:
        # 1. Первым делом получаем audio, как вы и сказали!
        audio, sr = librosa.load(file_path, sr=16000)

        # 2. Проверка длительности
        duration = len(audio) / sr
        if duration < 1.0:
            print(f"[-] Файл слишком короткий: {duration} сек.")
            result_payload = {
                "status": "failed",
                "reason": "audio_too_short"
            }
            redis_client.set(task_data["request_id"], json.dumps(result_payload), ex=3600)
            return  # Досрочно выходим, но блок finally всё равно выполнится!
        else:
            # 3. Расчет SNR и фильтрация
            snr_value = calculate_snr(audio)
            if snr_value < 5:
                audio = apply_wiener_filter(audio)

            # 4. Преобразуем в тензор и запускаем нейросеть
            audio_tensor = torch.from_numpy(audio).unsqueeze(0)
            prediction = model(audio_tensor)  # Передаем в нашу глобальную модель-заглушку
            verdict = "spoof" if prediction > 0.5 else "bonafide"
            result_payload = {
                "status": "completed",
                "prediction": prediction,
                "verdict": verdict
                }

            # Записываем в Redis: ключ — это request_id, значение — JSON-строка
            redis_client.set(task_data["request_id"], json.dumps(result_payload), ex=3600)

    except Exception as e:
        print(f"[!] Ошибка при обработке: {e}")

    finally:
        # 5. Чистим за собой диск в любом случае (даже если произошла ошибка)
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"[+] Временный файл удален: {file_path}")

        # Подтверждаем RabbitMQ, что задача удалена из очереди
        ch.basic_ack(delivery_tag=method.delivery_tag)


# --- Настройка подключения Потребителя ---
connection = pika.BlockingConnection(pika.ConnectionParameters(host='localhost'))
channel = connection.channel()
channel.queue_declare(queue='audio_processing_queue', durable=True)

# Указываем, какую функцию вызывать при получении сообщения
channel.basic_consume(queue='audio_processing_queue', on_message_callback=process_message)

print("[*] Воркер успешно запущен. Ожидание аудиозаписей...")
channel.start_consuming()  # Бесконечный цикл ожидания
