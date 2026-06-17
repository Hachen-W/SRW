# SRW

Цепочка функции `process_message()` в файле `worker.py`:
1. Получаем `file_path` и `request_id` из сообщения RabbitMQ.
2. Загружаем аудиозапись, проверяем SNR и переводим массив в тензор с батч-размерностью.
3. Пропускаем через модель-заглушку `model(audio_tensor)` и получаем `prediction`.
4. Записываем итоговый вердикт в Redis.

**Установка необходимых пакетов:**
```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### Запуск программы

**Директория:** `New_Sipuha`

**Команда:**
```bash
# Запускаем Redis (хранилище результатов)
sudo systemctl start redis-server

# Запускаем RabbitMQ (брокер очередей)
sudo systemctl start rabbitmq-server

# Запускаем фоновый воркер (Терминал №1)
source /home/hachen/SRW/venv/bin/activate
python core/worker.py

# Запускаем веб-шлюз FastAPI (Терминал №2)
source /home/hachen/SRW/venv/bin/activate
uvicorn main:app --reload
```
### Оценка метрик нейросетей

**Директория:** `New_Sipuha/core`

**Команды:**
```bash
python -m benchmarks.evaluate_streaming --model pyara --max_samples 1866
```

### Таймирование программы

**Директория:** `New_Sipuha/core`

**Команды:**
```bash
# Запускаем Redis (хранилище результатов)
sudo systemctl start redis-server

# Запускаем RabbitMQ (брокер очередей)
sudo systemctl start rabbitmq-server

# Запускаем фоновый воркер (Терминал №1)
source /home/hachen/SRW/venv/bin/activate
python worker.py

# Запускаем трассировку (Терминал №2)
source /home/hachen/SRW/venv/bin/activate
python -m benchmarks.timing_pytorch
```

### Запуск тренировки

**Директория:** `New_Sipuha/core`

**Команда:**
```bash
python -m models.train
```

### Система обнаружения подделки голоса

#### worker.py

**Технический конвейер:**
1. FastAPI,
2. RabbitMQ,
3. Worker,
4. Redis,

**Структура нейросети:**
1. Audio Wave
2. LFCC
3. CNN Layers
4. Global Max Pooling
5. Linear Classifier
6. Sigmoid
7. Verdict

#### train.py

**Тренировочный цикл:**
- Архитектура сети (DeepfakeDetector на базе LFCC и Global Max Pooling).
- Функция потерь (BCELoss — бинарная кросс-энтропия).
- Загрузчик данных (ASVspoofDataset и DataLoader с динамическим паддингом).
- Алгоритм оптимизации (Adam).

**Machine Learning Pipeline:**
- Датасет ASVspoof.
- Скрипт `train.py`.
- Файл весов (`weights.pth`).
- Загрузка в `worker.py`.
