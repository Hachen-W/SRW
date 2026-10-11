import os
import tempfile
import time
import wave

import librosa
import pyara.main
from .base import BaseDetector

TARGET_SR = 16000


class PyAraDetector(BaseDetector):
    """
    Детектор на основе внешней библиотеки PyAra.
    Ожидается, что pyara сама выполняет загрузку, препроцессинг и инференс.
    """

    # Порог для непрерывных предсказаний. Нужен потоковому воркеру.
    optimal_threshold = 0.5

    def predict(self, file_path) -> float:
        """Оценка по файлу. Библиотека умеет отдавать её тремя разными способами."""
        try:
            # А. Проверяем, поддерживает ли метод флаг возврата вероятностей
            return float(pyara.main.predict_audio(str(file_path), return_prob=True))
        except TypeError:
            pass
        try:
            # Б. Проверяем альтернативный метод (как predict_proba в sklearn)
            return float(pyara.main.predict_audio_proba(str(file_path)))
        except AttributeError:
            # В. Откат: библиотека жёстко отдаёт только 0 или 1
            return float(pyara.main.predict_audio(str(file_path)))

    def process_stream(self, audio_bytes: bytes) -> float:
        """Потоковый режим.

        PyAra работает только с файлом, поэтому накопленный буфер
        (16 кГц, моно, int16) сохраняется во временный wav.
        """
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = tmp.name
        try:
            with wave.open(path, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(TARGET_SR)
                wav_file.writeframes(audio_bytes)
            return self.predict(path)
        finally:
            if os.path.exists(path):
                os.remove(path)

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
        
        prediction = self.predict(file_path)

        t_inf = time.perf_counter() - start_time
        log_timing_callback(request_id, 'run_pyara_inference', duration, t_inf)

        # 3. Формирование результата
        # Задаем стандартный порог 0.5 для непрерывных предсказаний
        verdict = "spoof" if prediction >= self.optimal_threshold else "bonafide"

        return {
            "duration": duration,
            "prediction": float(prediction),
            "verdict": verdict
        }
