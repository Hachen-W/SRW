import asyncio
import aiohttp
import time
import statistics
from pathlib import Path

# Конфигурация теста
BASE_URL = "http://localhost:8000"
TEST_FILE_PATH = r"C:\Users\maksi\Downloads\ElevenLabs.wav"

# Более плавное увеличение нагрузки
CONCURRENT_USERS = [1]
REQUESTS_PER_USER = 100  # Еще меньше запросов на пользователя


class LoadTester:
    def __init__(self, base_url):
        self.base_url = base_url

    async def make_request(self, session, request_id, semaphore):
        """Отправляет запрос с использованием семафора"""
        async with semaphore:
            try:
                start_time = time.time()

                with open(TEST_FILE_PATH, 'rb') as f:
                    form_data = aiohttp.FormData()
                    form_data.add_field('file', f, filename=f'test_{request_id}.wav', content_type='audio/wav')

                    async with session.post(
                            f"{self.base_url}/upload/",
                            data=form_data,
                            timeout=60
                    ) as response:
                        response_text = await response.text()
                        end_time = time.time()

                        return {
                            'status_code': response.status,
                            'response_time': end_time - start_time,
                            'success': response.status == 200,
                            'response': response_text
                        }

            except Exception as e:
                return {
                    'status_code': 0,
                    'response_time': 0,
                    'success': False,
                    'error': str(e)
                }

    async def run_test(self, concurrent_users, requests_per_user):
        """Запускает тест с ограничением одновременных запросов"""
        print(f"\n=== Тестирование с {concurrent_users} пользователями ===")

        # Используем семафор для строгого ограничения
        semaphore = asyncio.Semaphore(concurrent_users)

        connector = aiohttp.TCPConnector(
            limit=concurrent_users + 10,
            limit_per_host=concurrent_users + 10,
            keepalive_timeout=30
        )

        timeout = aiohttp.ClientTimeout(total=120)

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            tasks = []
            total_requests = concurrent_users * requests_per_user

            # Создаем задачи
            for i in range(total_requests):
                task = self.make_request(session, i, semaphore)
                tasks.append(task)

            # Выполняем
            start_time = time.time()
            results = await asyncio.gather(*tasks)
            end_time = time.time()

            # Анализируем
            successful = [r for r in results if r['success']]
            failed = [r for r in results if not r['success']]
            response_times = [r['response_time'] for r in successful]

            test_duration = end_time - start_time
            rps = len(successful) / test_duration if test_duration > 0 else 0

            print(f"Всего запросов: {total_requests}")
            print(f"Успешных: {len(successful)}")
            print(f"Неудачных: {len(failed)}")
            print(f"Успешность: {len(successful) / total_requests * 100:.1f}%")
            print(f"Запросов в секунду: {rps:.2f}")

            if successful:
                avg_time = statistics.mean(response_times)
                print(f"Время ответа: {avg_time:.2f} сек в среднем")

                # Показываем распределение времени ответа
                if len(response_times) > 1:
                    print(f"Разброс: {min(response_times):.2f}-{max(response_times):.2f} сек")

            if failed:
                errors = list(set(r.get('error', 'Unknown') for r in failed))
                print(f"Ошибки ({len(errors)} типов): {errors[:2]}")  # Только 2 первые ошибки

            return {
                'concurrent_users': concurrent_users,
                'success_rate': len(successful) / total_requests * 100,
                'rps': rps,
                'avg_response_time': statistics.mean(response_times) if successful else 0
            }


async def main():
    if not Path(TEST_FILE_PATH).exists():
        print(f"Файл {TEST_FILE_PATH} не найден!")
        return

    tester = LoadTester(BASE_URL)

    print("=== НАГРУЗОЧНЫЙ ТЕСТ С ОПТИМИЗАЦИЕЙ ===")
    print("Сервер должен быть запущен с увеличенными лимитами!")

    results = []
    for users in CONCURRENT_USERS:
        result = await tester.run_test(users, REQUESTS_PER_USER)
        results.append(result)

        # Если успешность упала ниже 80%, останавливаемся
        if result['success_rate'] < 80 and users > 2:
            print(f"\n⚠️  Успешность ниже 80%, останавливаем тестирование")
            break

        # Пауза между тестами
        if users != CONCURRENT_USERS[-1]:
            pause = max(3, users)  # Динамическая пауза
            print(f"Пауза {pause} секунд...")
            await asyncio.sleep(pause)

    # Сводка
    print(f"\n{'=' * 60}")
    print("ФИНАЛЬНАЯ СВОДКА:")
    print(f"{'Пользователи':<12} {'Успешность':<12} {'RPS':<10} {'Ср. время':<12}")
    print("-" * 60)
    for r in results:
        print(
            f"{r['concurrent_users']:<12} {r['success_rate']:<11.1f}% {r['rps']:<10.1f} {r['avg_response_time']:<11.2f}сек")


if __name__ == "__main__":
    asyncio.run(main())