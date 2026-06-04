from abc import ABC, abstractmethod


class BaseDetector(ABC):
    @abstractmethod
    def process(
            self, file_path: str, request_id: str, log_timing_callback
            ) -> dict:
        """
        Метод должен возвращать словарь с результатами:
        {
            "duration": float,
            "prediction": float,
            "verdict": str ("spoof" | "bonafide")
        }
        """
        pass
