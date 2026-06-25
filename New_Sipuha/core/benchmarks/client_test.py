import asyncio
import websockets
import json
import os

# --- НАСТРОЙКИ ПОДКЛЮЧЕНИЯ ---
WS_URL = "ws://localhost:8000/audio/stream"
AUTH_TOKEN = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI2IiwianRpIjoiYWI5N2UzMWItODIwMi00MGE3LWEzMzEtOGI3NWJlM2ViM2U5IiwidHlwZSI6ImFjY2VzcyIsImZyZXNoIjpmYWxzZSwiY3NyZiI6Ijk5ZDA4ZDZkLWYwYzktNGUzNi1iYzU4LTQyYzhjMWNlNjYyZiIsImlhdCI6MTc4MDk2MjUzNiwiZXhwIjoxNzgwOTYzMTM2Ljg2OTE2Nywicm9sZSI6IkFETUlOIn0.yUZuASwirb0y5ZZ6kUGdhxf0Nj1QckcrhLdDILA7NAM"

# Путь к тестовому файлу (PCM 16-bit, 16кГц, моно)
AUDIO_FILE_PATH = "test_audio.wav" 

# Размер чанка: 500 мс при 16000 Гц (16000 * 2 байта на семпл * 0.5 сек = 16000 байт)
CHUNK_SIZE_BYTES = 16000 
STREAMING_INTERVAL = 0.5 # Отправка каждые 500 мс

async def send_audio_stream():
    # Формируем URL с токеном авторизации
    url_with_auth = f"{WS_URL}?token={AUTH_TOKEN.replace(' ', '%20')}"
    
    if not os.path.exists(AUDIO_FILE_PATH):
        print(f"[!] Файл {AUDIO_FILE_PATH} не найден. Положите файл в директорию со скриптом.")
        return

    print(f"[*] Установка соединения с {WS_URL}...")
    
    try:
        async with websockets.connect(url_with_auth) as websocket:
            print("[+] Соединение успешно установлено! Начинаем стриминг аудио...")

            # Функция для параллельного прослушивания ответов от сервера
            async def receive_responses():
                try:
                    async for message in websocket:
                        response = json.loads(message)
                        print(f"[Сервер] -> {response}")
                        
                        # Если сервер прислал сигнал прерывания
                        if response.get("status") == "terminated":
                            print("\n[🚨 КРИТ] Звонок принудительно оборван банком! Обнаружен дипфейк.")
                            break
                except websockets.exceptions.ConnectionClosed:
                    print("[*] Соединение закрыто сервером.")

            # Запускаем асинхронное чтение ответов в фоне
            listen_task = asyncio.create_task(receive_responses())

            # Читаем локальный файл и стримим его чанками в сокет
            with open(AUDIO_FILE_PATH, "rb") as f:
                while True:
                    chunk = f.read(CHUNK_SIZE_BYTES)
                    if not chunk:
                        print("[*] Файл полностью прочитан. Стриминг завершен.")
                        break
                    
                    # Отправляем строго бинарные байты (receive_bytes на стороне FastAPI)
                    await websocket.send(chunk)
                    
                    # Имитируем реальное время разговора (пауза между чанками)
                    await asyncio.sleep(STREAMING_INTERVAL)

            # Даем время дослушать финальные ответы, если они еще идут
            await asyncio.sleep(2)
            listen_task.cancel()

    except websockets.exceptions.InvalidStatusCode as e:
        if e.status_code == 4001:
            print("[!] Ошибка: Неверный или истекший JWT-токен (4001 Unauthorized).")
        elif e.status_code == 4003:
            print("[!] Ошибка: У пользователя нет прав SERVICE/ADMIN для стриминга (4003 Forbidden).")
        else:
            print(f"[!] Не удалось подключиться. Код ответа сервера: {e.status_code}")
    except Exception as e:
        print(f"[!] Непредвиденная ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(send_audio_stream())
