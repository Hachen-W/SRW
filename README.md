# SRW

Цепочка функции `process_message()` в файле `worker.py`:
1. Получаем `file_path` и `request_id` из сообщения RabbitMQ.
2. Загружаем аудиозапись, проверяем SNR и переводим массив в тензор с батч-размерностью.
3. Пропускаем через модель-заглушку `model(audio_tensor)` и получаем `prediction`.
4. Записываем итоговый вердикт в Redis.

Установка необходимых компонентов:
```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

Запуск программы:
```bash
# Запускаем Redis (хранилище результатов)
sudo systemctl start redis-server

# Запускаем RabbitMQ (брокер очередей)
sudo systemctl start rabbitmq-server

# Запускаем фоновый воркер (Терминал №1)
source /home/hachen/SRW/venv/bin/activate
python worker.py

# Запускаем веб-шлюз FastAPI (Терминал №2)
source /home/hachen/SRW/venv/bin/activate
uvicorn main:app --reload
```