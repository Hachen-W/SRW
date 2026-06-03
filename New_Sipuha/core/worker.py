import pika
import json
import librosa
import os
from scipy.signal import welch, wiener
import numpy as np
import torch
import torch.nn as nn
import torchaudio.transforms as T
from torch.utils.data import Dataset
from dotenv import load_dotenv
import redis
import time
import csv
import atexit
import uuid


# Глобальный буфер для накопления метрик (решение проблемы дискового I/O)
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


class ASVspoofDataset(Dataset):
    def __init__(self, protocols_file, audio_dir):
        self.audio_files = []
        self.labels = []

    def __len__(self):
        return len(self.audio_files)

    def __getitem__(self, idx):
        file_path = self.audio_files[idx]
        label = self.labels[idx]
        audio, _ = librosa.load(file_path, sr=16000)
        return torch.tensor(label, dtype=torch.float32)


class DeepfakeDetector(nn.Module):
    def __init__(self, sample_rate=16000, n_lfcc=40):
        super().__init__()
        self.lfcc_extractor = T.LFCC(
            sample_rate=sample_rate,
            n_lfcc=n_lfcc,
            log_lf=True,
            speckwargs={"n_fft": 400, "hop_length": 160}
        )
        self.conv_net = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=3, padding=1),
            nn.BatchNorm2d(16),
            nn.ReLU(),
            nn.MaxPool2d(kernel_size=2),
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.MaxPool2d(kernel_size=2),
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU()
        )
        self.global_pool = nn.AdaptiveMaxPool2d((1, 1))
        self.fc = nn.Linear(in_features=64, out_features=1)
        self.sigmoid = nn.Sigmoid()

    def forward(self, audio_tensor):
        lfcc_features = self.lfcc_extractor(audio_tensor)
        x = lfcc_features.unsqueeze(1)
        x = self.conv_net(x)
        x = self.global_pool(x)
        x = torch.flatten(x, start_dim=1)
        x = self.fc(x)
        prob = self.sigmoid(x)
        return prob


def load_audio_file(file_path):
    start_time = time.perf_counter()
    audio, sr = librosa.load(file_path, sr=16000)
    return audio, sr, time.perf_counter() - start_time


def save_result_to_redis(request_id, result_payload):
    start_time = time.perf_counter()
    redis_client.set(request_id, json.dumps(result_payload), ex=3600)
    return time.perf_counter() - start_time


def cleanup_temporary_file(file_path):
    if os.path.exists(file_path):
        os.remove(file_path)


def calculate_snr(audio):
    start_time = time.perf_counter()
    frequencies, psd = welch(audio, fs=16000, nperseg=320)
    speech_mask = (frequencies >= 300) & (frequencies <= 4000)
    power_signal = psd[speech_mask].sum()
    power_noise = psd[~speech_mask].sum()
    snr_val = float('inf') if power_noise == 0 else 10 * np.log10(power_signal / power_noise)
    return snr_val, time.perf_counter() - start_time


def apply_wiener_filter(audio):
    start_time = time.perf_counter()
    filtered = wiener(audio)
    return filtered, time.perf_counter() - start_time


def run_inference(audio, model):
    start_time = time.perf_counter()
    audio_tensor = torch.from_numpy(audio).unsqueeze(0).float()
    with torch.no_grad():
        prediction = model(audio_tensor).item()
    return prediction, time.perf_counter() - start_time


def process_message(ch, method, properties, body):
    e2e_start_time = time.perf_counter()
    task_data = json.loads(body)
    file_path = task_data["file_path"]
    request_id = task_data.get("request_id", str(uuid.uuid4()))

    print(f"[*] Началась обработка файла: {file_path}")
    audio = None
    duration = 0.0

    try:
        audio, sr, t_load = load_audio_file(file_path)
        duration = len(audio) / sr
        log_timing(request_id, 'load_audio_file', duration, t_load)

        if duration < 1.0:
            result_payload = {"status": "failed", "reason": "audio_too_short"}
            t_redis = save_result_to_redis(request_id, result_payload)
            log_timing(request_id, 'save_result_to_redis', duration, t_redis)
            return

        snr_value, t_snr = calculate_snr(audio)
        log_timing(request_id, 'calculate_snr', duration, t_snr)

        if snr_value < 5:
            audio, t_wiener = apply_wiener_filter(audio)
            log_timing(request_id, 'apply_wiener_filter', duration, t_wiener)

        prediction, t_inf = run_inference(audio, model)
        log_timing(request_id, 'run_inference', duration, t_inf)

        verdict = "spoof" if prediction > 0.5 else "bonafide"
        result_payload = {
            "status": "completed",
            "prediction": prediction,
            "verdict": verdict
            }

        t_redis = save_result_to_redis(request_id, result_payload)
        log_timing(request_id, 'save_result_to_redis', duration, t_redis)

    except Exception as e:
        print(f"[!] Ошибка при обработке: {e}")

    finally:
        cleanup_temporary_file(file_path)
        ch.basic_ack(delivery_tag=method.delivery_tag)

        # Логируем полное время обработки (End-to-End)
        e2e_total_time = time.perf_counter() - e2e_start_time
        log_timing(request_id, 'process_message_e2e', duration, e2e_total_time)


if __name__ == "__main__":
    load_dotenv()

    model = DeepfakeDetector()
    model.load_state_dict(torch.load('deepfake_model.pth'))
    model.eval()

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

    print("[*] Воркер успешно запущен. Ожидание аудиозаписей...")
    channel.start_consuming()
