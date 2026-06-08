import torch
import torch.nn as nn
from torch.utils.data import DataLoader, IterableDataset
import torch.nn.functional as F
from datasets import load_dataset, Audio

# Исправлено: Импортируем из общего модуля моделей для стабильного запуска
from models.pytorch_detector import DeepfakeDetector


class StreamingAudioDataset(IterableDataset):
    def __init__(self, hf_dataset_name, split="train", target_sr=16000, duration_sec=4):
        """
        Использует потоковую загрузку, не занимая место на жестком диске.
        """
        # 1. Загружаем датасет из облака в потоковом режиме
        self.dataset = load_dataset(hf_dataset_name, split=split, streaming=True)
        self.dataset = self.dataset.shuffle(buffer_size=1000, seed=42)
        
        # 2. Автоматический ресемплинг до 16000 Гц
        self.dataset = self.dataset.cast_column(
            "audio", Audio(sampling_rate=target_sr)
        )
        
        self.target_length = target_sr * duration_sec

    def process_data(self, dataset):
        for item in dataset:
            audio_array = item["audio"]["array"]
            label = item["label"] 
            
            waveform = torch.tensor(audio_array, dtype=torch.float32)

            # Безопасное приведение к моно
            if waveform.ndim > 1:
                if waveform.shape[0] < waveform.shape[1]:
                    waveform = torch.mean(waveform, dim=0)
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
    hf_dataset_name = "garystafford/deepfake-audio-detection" 

    print("[*] Подключение к потоковому датасету Hugging Face...")
    
    train_dataset = StreamingAudioDataset(
        hf_dataset_name=hf_dataset_name,
        split="train",
        target_sr=16000,
        duration_sec=4
    )

    train_loader = DataLoader(
        dataset=train_dataset,
        batch_size=32,
        collate_fn=my_collate_fn,
        num_workers=0
    )

    # Синхронизация устройств инференса и тренировки (CUDA -> MPS -> CPU)
    device = torch.device(
        'cuda' if torch.cuda.is_available()
        else 'mps' if torch.backends.mps.is_available()
        else 'cpu'
    )
    
    model = DeepfakeDetector().to(device)
    criterion = nn.BCELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.0003) # Немного подняли LR для адаптации 256 признаков

    # Настройка оптимизаций
    num_epochs = 10
    
    # Косинусный планировщик скорости обучения для плавной сходимости
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=num_epochs)
    
    # Скалер градиентов для AMP (смешанной точности) на CUDA
    use_amp = device.type == 'cuda'
    scaler = torch.amp.GradScaler('cuda', enabled=use_amp)

    model.train()
    print(f"[*] Начинаем обучение новой архитектуры на устройстве: {str(device).upper()}...")
    
    for epoch in range(num_epochs):
        running_loss = 0.0
        batches = 0
        current_lr = optimizer.param_groups[0]['lr']
        print(f"--- Эпоха {epoch+1}/{num_epochs} (Текущий LR: {current_lr:.6f}) ---")
        
        for padded_audios, labels_tensor in train_loader:
            padded_audios = padded_audios.to(device)
            labels_tensor = labels_tensor.to(device)

            optimizer.zero_grad()
            
            # Включаем Mixed Precision контекст, если тренируемся на GPU
            with torch.amp.autocast(device_type=device.type, enabled=use_amp):
                predictions = model(padded_audios)
                loss = criterion(predictions, labels_tensor)

            # Обратный проход через скалер градиентов
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()

            running_loss += loss.item()
            batches += 1
            
            if batches % 10 == 0:
                print(f"-> Батч: {batches}, Loss: {loss.item():.4f}")

        # Обновляем скорость обучения в конце каждой эпохи
        scheduler.step()

        epoch_loss = running_loss / batches if batches > 0 else 0
        print(f"==> Эпоха [{epoch+1}/{num_epochs}] завершена. Средний Loss: {epoch_loss:.4f}\n")

    # Сохраняем веса под обновленную структуру пулинга
    torch.save(model.state_dict(), 'models/deepfake_model.pth')
    print("💾 Обучение завершено! Новые веса успешно записаны в 'models/deepfake_model.pth'!")
