import csv
import atexit


class MetricsLogger:
    def __init__(self, log_file='metrics_log.csv', batch_size=10):
        self.log_file = log_file
        self.batch_size = batch_size
        self.buffer = []
        # Автоматически сбрасываем буфер при закрытии скрипта
        atexit.register(self.flush)

    def log_timing(self, request_id, func_name, audio_duration, exec_time):
        """Добавление записи в буфер метрик"""
        self.buffer.append([request_id, func_name, audio_duration, exec_time])
        if len(self.buffer) >= self.batch_size:
            self.flush()

    def flush(self):
        """Сброс накопленных метрик в файл"""
        if not self.buffer:
            return
        with open(self.log_file, mode='a', newline='') as f:
            writer = csv.writer(f)
            writer.writerows(self.buffer)
        self.buffer.clear()
