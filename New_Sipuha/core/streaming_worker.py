import os
import json
import redis
from dotenv import load_dotenv
from models.pytorch_detector import PyTorchDetector
from models.pyara_detector import PyAraDetector


# Константы конфигурации
TARGET_SR = 16000
ALPHA = 0.3                  # Коэффициент экспоненциального сглаживания (EMA)
MAX_BUFFER_SECONDS = 3       # Длина контекста для стабильного извлечения LFCC

# Обрывать ли сессию на первом вердикте spoof. Для IVR это нужно, для разбора
# записи целиком — мешает: кривая обрывается на первом срабатывании.
TERMINATE_ON_SPOOF = os.getenv("TERMINATE_ON_SPOOF", "true").lower() == "true"


class StreamingInferenceWorker:
    def __init__(self):
        load_dotenv()

        # Модели создаются при первом обращении: их выбирает клиент для каждой сессии
        self.default_model = os.getenv("MODEL_TYPE", "pytorch").lower()
        self.detectors = {}

        redis_host = os.getenv("REDIS_HOST", "localhost")
        # Два клиента: один для сырых байтов звука, второй для отправки ответов в формате JSON
        self.redis_raw = redis.Redis(host=redis_host, port=6379, db=0, decode_responses=False)
        self.redis_json = redis.Redis(host=redis_host, port=6379, db=0, decode_responses=True)

        # Буфер сессий в оперативной памяти (In-Memory)
        self.active_sessions = {}
        self.bytes_per_second = TARGET_SR * 2
        self.max_buffer_bytes = MAX_BUFFER_SECONDS * self.bytes_per_second

    def get_detector(self, name):
        """Возвращает модель по имени, создавая её при первом обращении."""
        name = (name or self.default_model).lower()
        if name not in ("pytorch", "pyara"):
            name = self.default_model
        if name not in self.detectors:
            print(f"[*] Инициализация модели для потока: {name}")
            self.detectors[name] = (
                PyAraDetector() if name == "pyara" else PyTorchDetector()
            )
        return self.detectors[name]

    def run(self):
        pubsub = self.redis_raw.pubsub()
        # Подписываемся на каналы аудиопотоков от FastAPI шлюза
        pubsub.psubscribe("stream:audio:*")
        print(f"[*] Стриминг-воркер запущен. Модель по умолчанию: {self.default_model}")

        for message in pubsub.listen():
            if message['type'] != 'pmessage':
                continue

            channel_name = message['channel'].decode('utf-8')
            session_id = channel_name.split(":")[-1]
            raw_data = message['data']

            # Проверяем управляющий сигнал завершения сессии (EOF)
            try:
                control_payload = json.loads(raw_data.decode('utf-8'))
                control = control_payload.get("control")
                if control == "EOF":
                    if session_id in self.active_sessions:
                        del self.active_sessions[session_id]
                        print(f"[*] Сессия {session_id} завершена. Буфер очищен.")
                    continue
                if control == "INIT":
                    # Клиент сообщил, какой моделью считать эту сессию
                    self.active_sessions[session_id] = {
                        "buffer": bytearray(),
                        "cumulative_score": 0.0,
                        "is_first": True,
                        "received_bytes": 0,
                        "model": control_payload.get("model")
                    }
                    self.get_detector(control_payload.get("model"))
                    continue
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass

            # Если сессия новая, то инициализируем под нее контекст в RAM
            if session_id not in self.active_sessions:
                self.active_sessions[session_id] = {
                    "buffer": bytearray(),
                    "cumulative_score": 0.0,
                    "is_first": True,
                    "received_bytes": 0,
                    "model": self.default_model
                }

            session = self.active_sessions[session_id]
            session["buffer"].extend(raw_data)
            session["received_bytes"] += len(raw_data)

            # Поддерживаем размер скользящего окна
            if len(session["buffer"]) > self.max_buffer_bytes:
                session["buffer"] = session["buffer"][-self.max_buffer_bytes:]

            # Защита от "холодного старта"
            if len(session["buffer"]) < self.bytes_per_second:
                continue

            # Передаем накопленный массив байт выбранной модели
            detector = self.get_detector(session.get("model"))
            current_score = detector.process_stream(bytes(session["buffer"]))

            # Расчет математики кумулятивной вероятности (EMA)
            if session["is_first"]:
                session["cumulative_score"] = current_score
                session["is_first"] = False
            else:
                session["cumulative_score"] = ALPHA * current_score + (1 - ALPHA) * session["cumulative_score"]

            # Классифицируем по валидационному порогу
            verdict = "spoof" if session["cumulative_score"] > detector.optimal_threshold else "bonafide"

            result_payload = {
                "status": "processing",
                "current_score": round(current_score, 4),
                "cumulative_score": round(session["cumulative_score"], 4),
                "verdict": verdict,
                "model": session.get("model") or self.default_model,
                # Позицию считает воркер: клиент не знает, насколько мы отстаём
                "position": round(session["received_bytes"] / self.bytes_per_second, 2)
            }

            if verdict == "spoof" and TERMINATE_ON_SPOOF:
                result_payload["status"] = "terminated"
                result_payload["reason"] = "Deepfake detected! Cutoff triggered."

            # Публикуем результат обратно в Redis канал для FastAPI шлюза
            result_channel = f"stream:result:{session_id}"
            self.redis_json.publish(result_channel, json.dumps(result_payload))
            
            # Если звонок принудительно оборван, стираем буфер сессии из памяти
            if (verdict == "spoof" and TERMINATE_ON_SPOOF
                    and session_id in self.active_sessions):
                del self.active_sessions[session_id]


if __name__ == "__main__":
    worker = StreamingInferenceWorker()
    worker.run()
