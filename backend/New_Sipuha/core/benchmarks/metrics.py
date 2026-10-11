import os
import argparse
import pandas as pd
from tqdm import tqdm

from models.pytorch_detector import PyTorchDetector
from models.pyara_detector import PyAraDetector


def dummy_callback(request_id, stage, duration, execution_time):
    """Заглушка для callback-лога таймингов, чтобы детекторы не падали"""
    pass


def main():
    parser = argparse.ArgumentParser(description="Валидация моделей антиспУфинга")
    parser.add_argument("--model", type=str, choices=["pytorch", "pyara"], required=True)
    parser.add_argument("--meta", type=str, default="validation_meta.csv", help="Путь к файлу метаданных")
    parser.add_argument("--output", type=str, default="evaluation_results.csv", help="Куда сохранить предсказания")
    args = parser.parse_args()

    # 1. Инициализация выбранной модели
    print(f"[*] Загрузка модели: {args.model}")
    if args.model == "pyara":
        detector = PyAraDetector()
    else:
        detector = PyTorchDetector()

    # 2. Чтение датасета
    df = pd.read_csv(args.meta)
    
    results = []

    # 3. Цикл предсказаний
    print("[*] Запуск инференса по датасету...")
    for idx, row in tqdm(df.iterrows(), total=len(df)):
        file_path = row['file_path']
        true_label = row['label']
        
        if not os.path.exists(file_path):
            print(f"[!] Файл не найден: {file_path}, пропускаем.")
            continue
            
        try:
            # Вызываем метод process напрямую
            res = detector.process(
                file_path=file_path, 
                request_id=f"val_{idx}", 
                log_timing_callback=dummy_callback
            )
            
            results.append({
                "file_path": file_path,
                "target": true_label,                 # Истинный класс (0 или 1)
                "prediction": res["prediction"],       # Вероятность или hard label
                "verdict": res["verdict"]             # Строковый вердикт
            })
        except Exception as e:
            print(f"[!] Ошибка при обработке {file_path}: {e}")

    # 4. Сохранение логов предсказаний
    df_res = pd.DataFrame(results)
    df_res.to_csv(args.output, index=False)
    print(f"[+] Результаты успешно сохранены в {args.output}")

if __name__ == "__main__":
    main()
