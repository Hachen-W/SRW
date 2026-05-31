import pika
import json
import librosa
import os
from scipy.signal import welch, wiener
import numpy as np
import torch
import torch.nn as nn
import torchaudio
import torchaudio.transforms as T
from torch.utils.data import Dataset, DataLoader
import os
from dotenv import load_dotenv
import redis
import time
import csv


def measure_time(func):
    def wrapper(*args, **kwargs):
        # Вычисляем длительность аудиосигнала из первого аргумента
        audio_duration = len(args[0]) / 16000 if args else 0

        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        execution_time = time.perf_counter() - start_time

        # Фиксируем данные в CSV-файл
        with open('benchmark_log.csv', mode='a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([func.__name__, audio_duration, execution_time])

        return result
    return wrapper


class ASVspoofDataset(Dataset):
    def __init__(self, protocols_file, audio_dir):
        # Здесь мы читаем файл разметки и сохраняем список путей и меток (0 или 1)
        self.audio_files = [] 
        self.labels = []
        # ... логика парсинга файла ...

    def __len__(self):
        return len(self.audio_files)

    def __getitem__(self, idx):
        # 1. Получаем путь к файлу и метку по индексу
        file_path = self.audio_files[idx]
        label = self.labels[idx]

        # 2. Загрузка аудио
        audio, _ = librosa.load(file_path, sr=16000)

        return audio_tensor, torch.tensor(label, dtype=torch.float32)


class DeepfakeDetector(nn.Module):
    def __init__(self, sample_rate=16000, n_lfcc=40):
        super().__init__()

        # 1. Извлечение признаков: Линейные кепстральные коэффициенты (LFCC)
        # speclog_lfcc=True применяет логарифмирование, чтобы выровнять масштаб энергий
        self.lfcc_extractor = T.LFCC(
            sample_rate=sample_rate,
            n_lfcc=n_lfcc,
            log_lf=True,
            speckwargs={"n_fft": 400, "hop_length": 160}
        )

        # 2. Блок сверточных слоев (CNN) для поиска частотно-временных артефактов
        self.conv_net = nn.Sequential(
            # Входной тензор: [Batch, 1, n_lfcc, Time_frames]
            nn.Conv2d(in_channels=1, out_channels=16, kernel_size=3, padding=1),
            nn.BatchNorm2d(16),  # Стабилизирует обучение и ускоряет сходимость
            nn.ReLU(),
            nn.MaxPool2d(kernel_size=2),  # Уменьшает размерность спектрограммы в 2 раза

            nn.Conv2d(in_channels=16, out_channels=32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.MaxPool2d(kernel_size=2),

            nn.Conv2d(in_channels=32, out_channels=64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU()
        )

        # 3. Глобальный адаптивный макс-пулинг (Global Max Pooling)
        # Схлопывает любую изменчивую ширину (время) и высоту в фиксированный размер 1x1
        self.global_pool = nn.AdaptiveMaxPool2d((1, 1))

        # 4. Полносвязный классификатор
        self.fc = nn.Linear(in_features=64, out_features=1)

        # 5. Функция активации Сигмоида
        self.sigmoid = nn.Sigmoid()

    def forward(self, audio_tensor):
        # Ожидаемый входной тензор от librosa: [Batch, Time] (например, [1, 80000])

        # Извлекаем признаки LFCC. Выход: [Batch, n_lfcc, Time_frames]
        lfcc_features = self.lfcc_extractor(audio_tensor)

        # Добавляем измерение каналов (Channels = 1) для Conv2d.
        # Выход: [Batch, 1, n_lfcc, Time_frames]
        x = lfcc_features.unsqueeze(1)

        # Пропускаем через сверточные слои
        x = self.conv_net(x)

        # Применяем глобальный пулинг. Выход: [Batch, 64, 1, 1]
        x = self.global_pool(x)

        # Выпрямляем тензор в вектор для полносвязного слоя. Выход: [Batch, 64]
        x = torch.flatten(x, start_dim=1)

        # Вычисляем логит классификатора
        x = self.fc(x)

        # Переводим в вероятность от 0.0 до 1.0
        prob = self.sigmoid(x)

        # Возвращаем обычное число float для совместимости с вашей логикой в Redis
        return prob


@measure_time
def calculate_snr(audio):
    frequencies, psd = welch(audio, fs=16000, nperseg=320)
    speech_mask = (frequencies >= 300) & (frequencies <= 4000)
    power_signal = psd[speech_mask].sum()
    power_noise = psd[~speech_mask].sum()
    if power_noise == 0:
        return float('inf')
    return 10 * np.log10(power_signal / power_noise)


@measure_time
def apply_wiener_filter(audio):
    return wiener(audio)


@measure_time
def run_inference(audio, model):
    # Преобразуем одномерный массив в тензор PyTorch
    audio_tensor = torch.from_numpy(audio).unsqueeze(0).float()
    # Выполняем инференс модели в режиме без расчета градиентов
    with torch.no_grad():
        return model(audio_tensor).item()


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
            audio_tensor = torch.from_numpy(audio).unsqueeze(0).float()
            # Передаем в нашу глобальную модель
            prediction = run_inference(audio, model)

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


if __name__ == "__main__":
    # Загружаем переменные из файла .env
    load_dotenv()

    # Инициализация модели
    model = DeepfakeDetector()
    model.load_state_dict(torch.load('deepfake_model.pth')) # Загружаем обученные веса
    model.eval()

    # Получаем адрес из окружения. Если его нет, используем 'localhost'
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_client = redis.Redis(host=redis_host, port=6379, db=0, decode_responses=True)

    # --- Настройка подключения Потребителя ---
    connection = pika.BlockingConnection(pika.ConnectionParameters(host='localhost'))
    channel = connection.channel()
    channel.queue_declare(queue='audio_processing_queue', durable=True)

    # Указываем, какую функцию вызывать при получении сообщения
    channel.basic_consume(queue='audio_processing_queue', on_message_callback=process_message)

    print("[*] Воркер успешно запущен. Ожидание аудиозаписей...")
    channel.start_consuming()  # Бесконечный цикл ожидания
