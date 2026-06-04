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
        # pyara.main.predict_audio возвращает 1 (spoof) или 0 (bonafide)
        decision = pyara.main.predict_audio(str(file_path))
        t_inf = time.perf_counter() - start_time
        log_timing_callback(request_id, 'run_pyara_inference', duration, t_inf)

        # 3. Формирование результата
        verdict = "spoof" if decision == 1 else "bonafide"

        return {
            "duration": duration,
            "prediction": float(decision),
            "verdict": verdict
        }
