import torch
import torch.nn as nn
from torch.utils.data import DataLoader, IterableDataset
import torch.nn.functional as F
from datasets import load_dataset, Audio

from models.pytorch_detector import DeepfakeDetector


class StreamingAudioDataset(IterableDataset):
    def __init__(self, hf_dataset_name, split="train", target_sr=16000, target_length=64600):
        """
        Использует потоковую загрузку и готовит аудио по стандарту бенчмарка Nes2Net
        (64,600 сэмплов, при нехватке — циклическое повторение tile-repeat).
        """
        self.dataset = load_dataset(hf_dataset_name, split=split, streaming=True)
        self.dataset = self.dataset.shuffle(buffer_size=1000, seed=42)
        
        # Автоматический ресемплинг до 16000 Гц
        self.dataset = self.dataset.cast_column(
            "audio", Audio(sampling_rate=target_sr)
        )
        
        # Вместо секунд жестко задаем длину в сэмплах
        self.target_length = target_length

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

            # Приведение к фиксированной длине (Спецификация: 64,600 samples)
            if waveform.shape[0] > self.target_length:
                waveform = waveform[:self.target_length]
            elif waveform.shape[0] < self.target_length:
                # Реализация tile-repeat (повторяем аудио вцикл, если оно короткое)
                repeats = (self.target_length + waveform.shape[0] - 1) // waveform.shape[0]
                waveform = waveform.repeat(repeats)[:self.target_length]

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
        target_length=64600  # Длина под стандарт Nes2Net Arena
    )

    train_loader = DataLoader(
        dataset=train_dataset,
        batch_size=32,
        collate_fn=my_collate_fn,
        num_workers=0
    )

    device = torch.device(
        'cuda' if torch.cuda.is_available()
        else 'mps' if torch.backends.mps.is_available()
        else 'cpu'
    )
    
    # Твоя модель снова в деле
    model = DeepfakeDetector().to(device)
    criterion = nn.BCELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.0003)

    num_epochs = 10
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=num_epochs)
    
    use_amp = device.type == 'cuda'
    scaler = torch.amp.GradScaler('cuda', enabled=use_amp)

    model.train()
    print(f"[*] Начинаем обучение твоей архитектуры на устройстве: {str(device).upper()}...")
    
    for epoch in range(num_epochs):
        running_loss = 0.0
        batches = 0
        current_lr = optimizer.param_groups[0]['lr']
        print(f"--- Эпоха {epoch+1}/{num_epochs} (Текущий LR: {current_lr:.6f}) ---")
        
        for padded_audios, labels_tensor in train_loader:
            padded_audios = padded_audios.to(device)
            labels_tensor = labels_tensor.to(device)

            optimizer.zero_grad()
            
            with torch.amp.autocast(device_type=device.type, enabled=use_amp):
                predictions = model(padded_audios)
                loss = criterion(predictions, labels_tensor)

            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()

            running_loss += loss.item()
            batches += 1
            
            if batches % 10 == 0:
                print(f"-> Батч: {batches}, Loss: {loss.item():.4f}")

        scheduler.step()

        epoch_loss = running_loss / batches if batches > 0 else 0
        print(f"==> Эпоха [{epoch+1}/{num_epochs}] завершена. Средний Loss: {epoch_loss:.4f}\n")

    torch.save(model.state_dict(), 'models/deepfake_model.pth')
    print("💾 Обучение завершено! Веса успешно записаны в 'models/deepfake_model.pth'!")
