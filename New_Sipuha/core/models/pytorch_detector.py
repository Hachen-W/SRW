import time
import os
import torch
import torch.nn as nn
import torchaudio
import torchaudio.transforms as T
import numpy as np
from scipy.signal import welch, wiener
from .base import BaseDetector


class DeepfakeDetector(nn.Module):
    """Архитектура модели с добавленной регуляризацией (Dropout)"""
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
            nn.Dropout2d(0.1),

            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.MaxPool2d(kernel_size=2),
            nn.Dropout2d(0.1),

            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.Dropout2d(0.2)
        )
        self.global_pool = nn.AdaptiveMaxPool2d((1, 1))

        self.fc = nn.Sequential(
            nn.Dropout(0.3),    # Оптимизация: дропаут перед финальным слоем
            nn.Linear(in_features=64, out_features=1)
        )
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
    def __init__(self, model_path=None):
        # Оптимизация: Поддержка GPU (CUDA или Apple Silicon MPS)
        self.device = torch.device(
            'cuda' if torch.cuda.is_available()
            else 'mps' if torch.backends.mps.is_available()
            else 'cpu'
        )

        if model_path is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            model_path = os.path.join(current_dir, 'deepfake_model.pth')

        self.model = DeepfakeDetector().to(self.device)

        if os.path.exists(model_path):
            self.model.load_state_dict(
                torch.load(model_path, map_location=self.device)
            )

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

        if np.var(audio) < 1e-10:
            return audio, time.perf_counter() - start_time

        dither = np.random.normal(0, 1e-8, audio.shape)
        audio_dithered = audio + dither

        filtered = wiener(audio_dithered)

        if np.isnan(filtered).any():
            filtered = np.nan_to_num(filtered)

        return filtered, time.perf_counter() - start_time

    def process(
            self, file_path: str, request_id: str, log_timing_callback
            ) -> dict:
        """
        Реализация интерфейса BaseDetector.
        """
        start_time = time.perf_counter()

        # Оптимизация: используем torchaudio вместо librosa
        waveform, sr = torchaudio.load(file_path)

        # Конвертация в моно при необходимости
        if waveform.shape[0] > 1:
            waveform = torch.mean(waveform, dim=0, keepdim=True)

        # Ресемплинг при необходимости
        if sr != 16000:
            resampler = T.Resample(orig_freq=sr, new_freq=16000)
            waveform = resampler(waveform)

        # Переводим в numpy для SciPy функций SNR и Wiener
        audio_np = waveform.squeeze().numpy()

        t_load = time.perf_counter() - start_time
        duration = len(audio_np) / 16000
        log_timing_callback(request_id, 'load_audio_file', duration, t_load)

        if duration < 1.0:
            raise ValueError("audio_too_short")

        # 2. Вычисление SNR
        snr_value, t_snr = self._calculate_snr(audio_np)
        log_timing_callback(request_id, 'calculate_snr', duration, t_snr)

        # 3. Применение фильтра Винера
        if snr_value < 5:
            audio_np, t_wiener = self._apply_wiener_filter(audio_np)
            log_timing_callback(
                request_id, 'apply_wiener_filter', duration, t_wiener
            )

        # 4. Инференс
        start_time = time.perf_counter()

        audio_tensor = torch.from_numpy(audio_np).unsqueeze(0).float().to(
            self.device
            )

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
