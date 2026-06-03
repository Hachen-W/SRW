import torch
import numpy as np
import uuid
import time
from datasets import load_dataset, Audio
from worker import calculate_snr, run_inference, \
    DeepfakeDetector, log_timing, flush_metrics


print("[*] Инициализация модели...")
model = DeepfakeDetector()
model.load_state_dict(torch.load('deepfake_model.pth'))
model.eval()

print("[*] Прогрев PyTorch (Warm-up)...")
# Создаем 1 секунду тишины для первого прохода
dummy_audio = np.zeros(16000, dtype=np.float32)
_, _ = calculate_snr(dummy_audio)
_, _ = run_inference(dummy_audio, model)

print("[*] Подключение к датасету...")
dataset = load_dataset(
    "kijjjj/audio_data_russian", split="train", streaming=True
    )
dataset = dataset.cast_column("audio", Audio(sampling_rate=16000))

print("[*] Запуск хронометража выборки...")
for i, sample in enumerate(dataset.take(20)):
    req_id = str(uuid.uuid4())
    audio_array = sample["audio"]["array"]
    duration = len(audio_array) / 16000.0
    text_preview = sample['text'][:30] if sample['text'] else "Без текста"

    print(
        f"Обработка трека {i+1}: '{text_preview}...' \
        (Спикер: {sample['speaker_name']})"
        )

    try:
        # Замеряем End-to-End для конкретного прогона
        e2e_start = time.perf_counter()

        snr_value, t_snr = calculate_snr(audio_array)
        log_timing(req_id, 'calculate_snr', duration, t_snr)

        prediction, t_inf = run_inference(audio_array, model)
        log_timing(req_id, 'run_inference', duration, t_inf)

        e2e_time = time.perf_counter() - e2e_start
        log_timing(req_id, 'timing_script_e2e', duration, e2e_time)

    except Exception as e:
        print(f"Ошибка при обработке индекса {i}: {e}")

# Принудительно сбрасываем буфер метрик
flush_metrics()

print("[+] Прогон завершен! Данные записаны в benchmark_log.csv")
