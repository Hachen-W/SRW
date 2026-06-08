import os
import tempfile
import argparse
import torch
import torchaudio
import pandas as pd
import numpy as np
from tqdm import tqdm
from datasets import load_dataset, Audio

# Импорт метрик
from sklearn.metrics import roc_curve, auc, accuracy_score, precision_score, recall_score, f1_score
from scipy.optimize import brentq
from scipy.interpolate import interp1d

# Импорт ваших детекторов
from models.pytorch_detector import PyTorchDetector
from models.pyara_detector import PyAraDetector


def dummy_callback(request_id, stage, duration, execution_time):
    """Заглушка для сервис-логов таймингов внутри моделей"""
    pass


def compute_eer(y_true, y_scores):
    """Вычисляет Equal Error Rate (EER) и оптимальный порог разделения"""
    fpr, tpr, thresholds = roc_curve(y_true, y_scores, pos_label=1)
    fnr = 1 - tpr
    eer = brentq(lambda x: 1.0 - x - interp1d(fpr, tpr)(x), 0.0, 1.0)
    thresh = interp1d(fpr, thresholds)(eer)
    return eer, thresh


def main():
    parser = argparse.ArgumentParser(description="Потоковая валидация моделей антиспУфинга")
    parser.add_argument("--model", type=str, choices=["pytorch", "pyara"], default="pytorch")
    parser.add_argument("--dataset", type=str, default="garystafford/deepfake-audio-detection")
    
    parser.add_argument("--split", type=str, default="train", help="Какой сплит валидировать")
    parser.add_argument("--max_samples", type=int, default=None, help="None — прогнать весь датасет")
    
    # Автоматическое имя лога на основе имени модели
    parser.add_argument("--output", type=str, default=None, help="Путь к файлу результатов (по умолчанию подставит имя модели)")
    args = parser.parse_args()

    # Динамически формируем имя файла лога
    if args.output is None:
        args.output = f"streaming_val_results_{args.model}.csv"

    # Инициализация детектора
    print(f"[*] Загрузка модели: {args.model.upper()}")
    detector = PyAraDetector() if args.model == "pyara" else PyTorchDetector()

    # Подключение к потоковому датасету
    target_sr = 16000
    print(f"[*] Подключение к HF датасету '{args.dataset}' (сплит: {args.split})...")
    dataset = load_dataset(args.dataset, split=args.split, streaming=True)
    dataset = dataset.cast_column("audio", Audio(sampling_rate=target_sr))

    results = []
    
    # Создаем временную директорию для изолированной работы с файлом
    with tempfile.TemporaryDirectory() as tmpdir:
        print("[*] Запуск валидационного инференса...")
        
        # ОПТИМИЗАЦИЯ: Один фиксированный путь для файла на весь жизненный цикл скрипта
        temp_file_path = os.path.join(tmpdir, "current_sample.wav")
        
        for idx, item in enumerate(tqdm(dataset, desc="Processing audio")):
            if args.max_samples is not None and idx >= args.max_samples:
                break

            audio_array = item["audio"]["array"]
            true_label = item["label"]

            # Конвертируем в тензор (формат torchaudio: [channels, time])
            waveform = torch.tensor(audio_array, dtype=torch.float32).unsqueeze(0)
            
            try:
                # Новые аудиоданные просто затирают старые в одном и том же файле
                torchaudio.save(temp_file_path, waveform, target_sr)

                # Прогоняем через интерфейс process вашего детектора
                res = detector.process(
                    file_path=temp_file_path,
                    request_id=f"streaming_val_{idx}",
                    log_timing_callback=dummy_callback
                )

                results.append({
                    "idx": idx,
                    "target": int(true_label),
                    "prediction": res["prediction"],
                    "verdict": res["verdict"]
                })

            except ValueError as ve:
                print(f"\n[!] Пропущен файл {idx}: {ve}")
            except Exception as e:
                print(f"\n[!] Непредвиденная ошибка на элементе {idx}: {e}")

    # Сохранение логов предсказаний
    df_res = pd.DataFrame(results)
    df_res.to_csv(args.output, index=False)
    print(f"[+] Логи предсказаний сохранены в {args.output}")

    # Расчет и вывод метрик
    y_true = df_res['target'].values
    y_scores = df_res['prediction'].values
    y_pred_binary = (y_scores >= 0.5).astype(int)

    print("\n" + "="*30 + " РЕЗУЛЬТАТЫ ВАЛИДАЦИИ " + "="*30)
    print(f"Всего успешно обработано файлов: {len(df_res)}")
    print(f"Accuracy:  {accuracy_score(y_true, y_pred_binary):.4f}")
    print(f"Precision: {precision_score(y_true, y_pred_binary, zero_division=0):.4f}")
    print(f"Recall:    {recall_score(y_true, y_pred_binary, zero_division=0):.4f}")
    print(f"F1-Score:  {f1_score(y_true, y_pred_binary, zero_division=0):.4f}")

    try:
        fpr, tpr, _ = roc_curve(y_true, y_scores)
        print(f"ROC-AUC:   {auc(fpr, tpr):.4f}")
        
        eer, opt_thresh = compute_eer(y_true, y_scores)
        print(f"EER:       {eer * 100:.2f}% (Оптимальный порог: {opt_thresh:.4f})")
    except Exception as e:
        print("[!] Не удалось рассчитать EER/AUC. (Если тестировалась модель PyAra, она возвращает только жесткие 0 или 1)")


if __name__ == "__main__":
    main()
