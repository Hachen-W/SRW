import torch
import torch.nn as nn
from torch.utils.data import DataLoader, IterableDataset
import torch.nn.functional as F
from datasets import load_dataset, Audio
from models.pytorch_detector import DeepfakeDetector


class StreamingAudioDataset(IterableDataset):
    def __init__(self, hf_dataset_name, split="train", target_sr=16000, duration_sec=4):
        """
        Использует потоковую загрузку, не занимая место на жестком диске.
        """
        # 1. Загружаем датасет из облака в потоковом режиме
        self.dataset = load_dataset(hf_dataset_name, split=split, streaming=True)
        self.dataset = self.dataset.shuffle(buffer_size=1000, seed=42)
        
        # 2. Оставляем только автоматический ресемплинг до 16000 Гц
        self.dataset = self.dataset.cast_column(
            "audio", Audio(sampling_rate=target_sr)
        )
        
        self.target_length = target_sr * duration_sec

    def process_data(self, dataset):
        for item in dataset:
            # Извлекаем numpy-массив со звуком и метку
            audio_array = item["audio"]["array"]
            label = item["label"] 
            
            # Конвертируем в PyTorch тензор
            waveform = torch.tensor(audio_array, dtype=torch.float32)

            # Безопасное приведение к моно, если аудио оказалось многоканальным (стерео)
            if waveform.ndim > 1:
                # Если форма (channels, time), усредняем по нулевой оси
                if waveform.shape[0] < waveform.shape[1]:
                    waveform = torch.mean(waveform, dim=0)
                # Если форма (time, channels), усредняем по первой оси
                else:
                    waveform = torch.mean(waveform, dim=1)

            # Приведение к фиксированной длине (Padding / Truncation)
            if waveform.shape[0] > self.target_length:
                waveform = waveform[:self.target_length]
            elif waveform.shape[0] < self.target_length:
                pad_amount = self.target_length - waveform.shape[0]
                waveform = F.pad(waveform, (0, pad_amount))

            yield waveform, torch.tensor(label, dtype=torch.float32)

    def __iter__(self):
        return self.process_data(self.dataset)


def my_collate_fn(batch):
    audios, labels = zip(*batch)
    padded_audios = torch.stack(audios)
    labels_tensor = torch.stack(labels).unsqueeze(1)
    return padded_audios, labels_tensor


if __name__ == '__main__':
    # Используем открытый датасет с Hugging Face вместо Kaggle
    hf_dataset_name = "garystafford/deepfake-audio-detection" 

    print("Подключение к потоковому датасету Hugging Face...")
    
    # Инициализация датасета
    train_dataset = StreamingAudioDataset(
        hf_dataset_name=hf_dataset_name,
        split="train",
        target_sr=16000,
        duration_sec=4
    )

    # ВАЖНО: При использовании IterableDataset параметр shuffle=True не поддерживается,
    # а num_workers лучше оставить 0 (чтобы потоки не скачивали одни и те же данные)
    train_loader = DataLoader(
        dataset=train_dataset,
        batch_size=32,
        collate_fn=my_collate_fn,
        num_workers=0
    )

    # Инициализация модели, устройства и оптимизатора
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = DeepfakeDetector().to(device)
    criterion = nn.BCELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.0001)

    num_epochs = 10
    model.train()

    print(f"Начинаем обучение на {device}...")
    
    for epoch in range(num_epochs):
        running_loss = 0.0
        batches = 0
        
        # Данные будут скачиваться и обрабатываться батч за батчем
        for padded_audios, labels_tensor in train_loader:
            padded_audios = padded_audios.to(device)
            labels_tensor = labels_tensor.to(device)

            optimizer.zero_grad()
            predictions = model(padded_audios)
            loss = criterion(predictions, labels_tensor)
            loss.backward()
            optimizer.step()

            running_loss += loss.item()
            batches += 1
            
            # Печатаем прогресс каждые 10 батчей
            if batches % 10 == 0:
                print(f"Эпоха [{epoch+1}/{num_epochs}], Батч: {batches}, Loss: {loss.item():.4f}")

        # Средний loss за эпоху
        epoch_loss = running_loss / batches if batches > 0 else 0
        print(f"==> Эпоха [{epoch+1}/{num_epochs}] завершена. Средняя Ошибка (Loss): {epoch_loss:.4f}\n")

    torch.save(model.state_dict(), 'deepfake_model.pth')
    print("💾 Обучение завершено! Веса успешно сохранены в файл 'deepfake_model.pth'!")
