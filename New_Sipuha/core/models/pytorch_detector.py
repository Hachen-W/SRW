import time
import librosa
import torch
import torch.nn as nn
import torchaudio.transforms as T
import numpy as np
from scipy.signal import welch, wiener
from .base import BaseDetector


class DeepfakeDetector(nn.Module):
    """Архитектура модели из исходного worker.py"""
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


class PyTorchDetector(BaseDetector):
    def __init__(self, model_path='deepfake_model.pth'):
        self.model = DeepfakeDetector()
        self.model.load_state_dict(torch.load(model_path))
        self.model.eval()

    def _calculate_snr(self, audio):
        """Вспомогательный метод для вычисления SNR"""
        start_time = time.perf_counter()
        frequencies, psd = welch(audio, fs=16000, nperseg=320)
        speech_mask = (frequencies >= 300) & (frequencies <= 4000)
        power_signal = psd[speech_mask].sum()
        power_noise = psd[~speech_mask].sum()
        snr_val = float('inf') if power_noise == 0 else 10 * np.log10(power_signal / power_noise)
        return snr_val, time.perf_counter() - start_time

    def _apply_wiener_filter(self, audio):
        """Вспомогательный метод для применения фильтра Винера"""
        start_time = time.perf_counter()

        # 1. Если аудио — это полная тишина, возвращаем его как есть
        if np.var(audio) < 1e-10:
            return audio, time.perf_counter() - start_time

        # 2. Добавляем микроскопический шум (dithering)
        # для защиты от деления на ноль
        dither = np.random.normal(0, 1e-8, audio.shape)
        audio_dithered = audio + dither

        # 3. Применяем фильтр
        filtered = wiener(audio_dithered)

        # 4. Если SciPy все же выдал NaN, заменяем их на нули
        if np.isnan(filtered).any():
            filtered = np.nan_to_num(filtered)

        return filtered, time.perf_counter() - start_time

    def process(
            self, file_path: str, request_id: str, log_timing_callback
            ) -> dict:
        """
        Реализация интерфейса BaseDetector.
        """
        # 1. Загрузка аудио
        start_time = time.perf_counter()
        audio, sr = librosa.load(file_path, sr=16000)
        t_load = time.perf_counter() - start_time
        duration = len(audio) / sr
        log_timing_callback(request_id, 'load_audio_file', duration, t_load)

        if duration < 1.0:
            raise ValueError("audio_too_short")

        # 2. Вычисление SNR
        snr_value, t_snr = self._calculate_snr(audio)
        log_timing_callback(request_id, 'calculate_snr', duration, t_snr)

        # 3. Применение фильтра Винера (опционально, если SNR низкий)
        if snr_value < 5:
            audio, t_wiener = self._apply_wiener_filter(audio)
            log_timing_callback(
                request_id, 'apply_wiener_filter', duration, t_wiener
                )

        # 4. Инференс
        start_time = time.perf_counter()
        audio_tensor = torch.from_numpy(audio).unsqueeze(0).float()
        with torch.no_grad():
            prediction = self.model(audio_tensor).item()
        t_inf = time.perf_counter() - start_time
        log_timing_callback(request_id, 'run_inference', duration, t_inf)

        # Формирование результата
        verdict = "spoof" if prediction > 0.5 else "bonafide"

        return {
            "duration": duration,
            "prediction": prediction,
            "verdict": verdict
        }
