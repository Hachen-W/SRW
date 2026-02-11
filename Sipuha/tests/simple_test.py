import requests
import time


def test_single():
    """Тест одного запроса"""
    url = "http://localhost:8000/upload/"

    with open(r"C:\Users\maksi\Downloads\ElevenLabs.wav", 'rb') as f:
        files = {'file': ('test.wav', f, 'audio/wav')}

        start = time.time()
        try:
            response = requests.post(url, files=files, timeout=30)
            print(f"Статус: {response.status_code}")
            print(f"Время: {time.time() - start:.2f}с")
            print(f"Ответ: {response.text[:100]}...")
        except Exception as e:
            print(f"Ошибка: {e}")


if __name__ == "__main__":
    test_single()