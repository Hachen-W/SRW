import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from worker import DeepfakeDetector
import numpy as np
from torch.utils.data import Dataset


class MockAudioDataset(Dataset):
    def __init__(self, num_samples=100):
        self.num_samples = num_samples

    def __len__(self):
        return self.num_samples

    def __getitem__(self, idx):
        # Имитируем 1 секунду аудио (16000 отсчетов)
        fake_audio = np.random.rand(16000)
        # Генерируем случайную метку (0 или 1)
        fake_label = np.random.randint(0, 2)
        return fake_audio, fake_label


def my_collate_fn(batch):
    audios, labels = zip(*batch)
    audio_tensors = [torch.from_numpy(a).float() for a in audios]
    # Выравниваем нулями до самого длинного трека в батче
    padded_audios = torch.nn.utils.rnn.pad_sequence(
        audio_tensors, batch_first=True
        )
    # Добавляем размерность [Batch, 1] для корректной работы BCELoss
    labels_tensor = torch.tensor(labels, dtype=torch.float32).unsqueeze(1)
    return padded_audios, labels_tensor


if __name__ == '__main__':
    # 1. Настройка путей к вашему датасету ASVspoof
    train_dataset = MockAudioDataset(num_samples=128)

    train_loader = DataLoader(
        dataset=train_dataset,
        batch_size=32,
        shuffle=True,
        collate_fn=my_collate_fn
    )

    # 2. Инициализация компонентов сети
    model = DeepfakeDetector()
    criterion = nn.BCELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.0001)

    # 3. Цикл обучения
    num_epochs = 50
    model.train()  # Переводим модель в режим обучения

    for epoch in range(num_epochs):
        running_loss = 0.0
        for padded_audios, labels_tensor in train_loader:
            optimizer.zero_grad()                      # Сброс градиентов
            predictions = model(padded_audios)         # Прямой проход
            loss = criterion(predictions, labels_tensor)  # Расчет ошибки
            loss.backward()                            # Обратный проход
            optimizer.step()                           # Обновление весов

            running_loss += loss.item()

        epoch_loss = running_loss / len(train_loader)
        print(
            f"Эпоха [{epoch+1}/{num_epochs}], Ошибка (Loss): {epoch_loss:.4f}"
            )

    # 4. Сохранение результатов
    torch.save(model.state_dict(), 'deepfake_model.pth')
    print("💾 Веса успешно сохранены в файл 'deepfake_model.pth'!")
