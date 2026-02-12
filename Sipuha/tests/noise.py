import noisereduce as nr
import librosa
import soundfile as sf

def reduce_noise_simple(input_file, output_file, noise_start=0, noise_end=1):
    # Загружаем аудио
    audio, sr = librosa.load(input_file, sr=None)
    
    # Берем образец шума из первых секунд
    noise_sample = audio[noise_start * sr:noise_end * sr]
    
    # Применяем шумоподавление
    reduced_noise = nr.reduce_noise(
        y=audio,
        sr=sr,
        y_noise=noise_sample,
        prop_decrease=0.8,  # степень уменьшения шума
        n_fft=2048,
        win_length=2048,
        hop_length=512
    )
    
    # Сохраняем результат
    sf.write(output_file, reduced_noise, sr)
    print(f"Очищенное аудио сохранено в {output_file}")
