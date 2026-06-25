import os
import json
import redis
from dotenv import load_dotenv
from models.pytorch_detector import PyTorchDetector


# Константы конфигурации
TARGET_SR = 16000
ALPHA = 0.3                  # Коэффициент экспоненциального сглаживания (EMA)
MAX_BUFFER_SECONDS = 3       # Длина контекста для стабильного извлечения LFCC


class StreamingInferenceWorker:
    def __init__(self):
        load_dotenv()
        print("[*] Инициализация PyTorchDetector для потокового режима...")

        # Инициализируем модель один раз при старте воркера
        self.detector = PyTorchDetector()

        redis_host = os.getenv("REDIS_HOST", "localhost")
        # Два клиента: один для сырых байтов звука, второй для отправки ответов в формате JSON
        self.redis_raw = redis.Redis(host=redis_host, port=6379, db=0, decode_responses=False)
        self.redis_json = redis.Redis(host=redis_host, port=6379, db=0, decode_responses=True)

        # Буфер сессий в оперативной памяти (In-Memory)
        self.active_sessions = {}
        self.bytes_per_second = TARGET_SR * 2
        self.max_buffer_bytes = MAX_BUFFER_SECONDS * self.bytes_per_second

    def run(self):
        pubsub = self.redis_raw.pubsub()
        # Подписываемся на каналы аудиопотоков от FastAPI шлюза
        pubsub.psubscribe("stream:audio:*")
        print(f"[*] Стриминг-воркер запущен. Порог отсечения: {self.detector.optimal_threshold}")

        for message in pubsub.listen():
            if message['type'] != 'pmessage':
                continue

            channel_name = message['channel'].decode('utf-8')
            session_id = channel_name.split(":")[-1]
            raw_data = message['data']

            # Проверяем управляющий сигнал завершения сессии (EOF)
            try:
                control_payload = json.loads(raw_data.decode('utf-8'))
                if control_payload.get("control") == "EOF":
                    if session_id in self.active_sessions:
                        del self.active_sessions[session_id]
                        print(f"[*] Сессия {session_id} завершена. Буфер очищен.")
                    continue
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass

            # Если сессия новая, то инициализируем под нее контекст в RAM
            if session_id not in self.active_sessions:
                self.active_sessions[session_id] = {
                    "buffer": bytearray(),
                    "cumulative_score": 0.0,
                    "is_first": True
                }

            session = self.active_sessions[session_id]
            session["buffer"].extend(raw_data)

            # Поддерживаем размер скользящего окна
            if len(session["buffer"]) > self.max_buffer_bytes:
                session["buffer"] = session["buffer"][-self.max_buffer_bytes:]

            # Защита от "холодного старта"
            if len(session["buffer"]) < self.bytes_per_second:
                continue

            # Передаем накопленный массив байт
            current_score = self.detector.process_stream(bytes(session["buffer"]))

            # Расчет математики кумулятивной вероятности (EMA)
            if session["is_first"]:
                session["cumulative_score"] = current_score
                session["is_first"] = False
            else:
                session["cumulative_score"] = ALPHA * current_score + (1 - ALPHA) * session["cumulative_score"]

            # Классифицируем по валидационному порогу
            verdict = "spoof" if session["cumulative_score"] > self.detector.optimal_threshold else "bonafide"

            result_payload = {
                "status": "processing",
                "current_score": round(current_score, 4),
                "cumulative_score": round(session["cumulative_score"], 4),
                "verdict": verdict
            }

            if verdict == "spoof":
                result_payload["status"] = "terminated"
                result_payload["reason"] = "Deepfake detected! Cutoff triggered."

            # Публикуем результат обратно в Redis канал для FastAPI шлюза
            result_channel = f"stream:result:{session_id}"
            self.redis_json.publish(result_channel, json.dumps(result_payload))
            
            # Если звонок принудительно оборван, стираем буфер сессии из памяти
            if verdict == "spoof" and session_id in self.active_sessions:
                del self.active_sessions[session_id]


if __name__ == "__main__":
    worker = StreamingInferenceWorker()
    worker.run()
