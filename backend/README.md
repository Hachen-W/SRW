# Запуск всей системы одной командой

## Расположение

```
study/
├── docker-compose.yml     ← этот файл
├── .env
├── auth-service/          ← репозиторий аутентификации
└── New_Sipuha/            ← репозиторий аудио-сервиса
```

Если репозитории лежат иначе, поправьте `AUTH_PATH` и `AUDIO_PATH` в `.env` —
пути указываются относительно этого файла.

## Запуск

```bash
cp .env.example .env
# вписать JWT_SECRET_KEY: openssl rand -hex 32
docker compose up -d --build
docker compose ps            # должно быть 7 контейнеров
```

- Аудио-сервис: http://localhost:8000/docs
- Аутентификация: http://localhost:8001/docs
- RabbitMQ: http://localhost:15672 (guest / guest)

## Что здесь передаётся автоматически

- **JWT_SECRET_KEY** задаётся один раз в `.env` рядом с этим файлом и уходит
  обоим сервисам. В `.env` самих проектов его прописывать не нужно, и они
  не могут разойтись. Если секрет не задан, compose откажется стартовать
  с понятным сообщением.
- **Адреса сервисов** подставляются по именам контейнеров: аудио-сервис
  видит `auth-redis`, `rabbitmq` и `redis` без указания IP.
- **Отзыв токенов при выходе** включён: аудио-сервис ходит в Redis
  аутентификации, поэтому logout сразу перестаёт пускать выданные токены.
  При раздельном запуске это работает только с отдельной надстройкой.

## Первый пользователь

```bash
curl -X POST http://localhost:8001/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","email":"demo@example.com","password":"demo"}'
```

Проверка сквозного сценария:

```bash
TOKEN=$(curl -s -X POST http://localhost:8001/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","password":"demo"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -X POST http://localhost:8000/audio/detect \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@запись.wav" -F "model=pytorch"
```

Вернулся `request_id` — цепочка работает.

## Настольный клиент

Запускается на хосте, в контейнеры не заводится. В `config.py` два адреса:

```python
BASE_URL = "http://localhost:8000"    # анализ
AUTH_URL = "http://localhost:8001"    # логин
```

## Отдельный запуск

Каждый проект по-прежнему поднимается своим `docker-compose.yml` — этот файл
их не заменяет. Тогда секрет придётся задавать в обоих `.env` вручную,
и следить, чтобы значения совпадали.

## Полезное

```bash
docker compose logs -f worker stream-worker   # признаки жизни воркеров
docker compose down                            # остановить всё
docker compose down -v                         # и стереть базу с очередью
docker compose up -d --build api               # пересобрать только аудио-сервис
```
