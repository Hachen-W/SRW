import time
import librosa
import pyara.main
from .base import BaseDetector


class PyAraDetector(BaseDetector):
    """
    Детектор на основе внешней библиотеки PyAra.
    Ожидается, что pyara сама выполняет загрузку, препроцессинг и инференс.
    """

    def process(
            self, file_path: str, request_id: str, log_timing_callback
            ) -> dict:
        """
        Реализация интерфейса BaseDetector для PyAra.
        """
        # 1. Получение длительности аудио (без полной загрузки файла в память)
        start_time = time.perf_counter()
        duration = librosa.get_duration(path=file_path)
        t_duration = time.perf_counter() - start_time
        log_timing_callback(
            request_id, 'get_audio_duration', duration, t_duration
            )

        # Отсеиваем слишком короткие записи
        if duration < 1.0:
            raise ValueError("audio_too_short")

        # 2. Инференс через библиотеку PyAra
        start_time = time.perf_counter()
        
        # Пытаемся вытащить непрерывную вероятность (0.0 - 1.0) с помощью безопасного перебора:
        try:
            # А. Проверяем, поддерживает ли метод флаг возврата вероятностей
            prediction = pyara.main.predict_audio(str(file_path), return_prob=True)
        except TypeError:
            try:
                # Б. Проверяем, есть ли альтернативный метод для вероятностей (как predict_proba в sklearn)
                prediction = pyara.main.predict_audio_proba(str(file_path))
            except AttributeError:
                # В. Откат: если библиотека жестко отдает только 0 или 1, забираем как есть
                decision = pyara.main.predict_audio(str(file_path))
                prediction = float(decision)

        t_inf = time.perf_counter() - start_time
        log_timing_callback(request_id, 'run_pyara_inference', duration, t_inf)

        # 3. Формирование результата
        # Задаем стандартный порог 0.5 для непрерывных предсказаний
        verdict = "spoof" if prediction >= 0.5 else "bonafide"

        return {
            "duration": duration,
            "prediction": float(prediction),
            "verdict": verdict
        }
