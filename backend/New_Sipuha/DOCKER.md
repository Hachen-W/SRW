# Запуск в контейнерах

Файлы лежат в корне репозитория, рядом с `main.py`:

```
New_Sipuha/
├── docker-compose.yml
├── docker-compose.auth-link.yml
├── .env
├── .dockerignore
├── deploy/Dockerfile
├── main.py
├── routes/  services/  settings/  core/
```

## Запуск

```bash
cp .env.example .env      # заполнить JWT_SECRET_KEY
docker compose up --build
```

Первая сборка долгая: torch тянет около гигабайта даже в CPU-варианте.

- API и документация: http://localhost:8000/docs
- RabbitMQ: http://localhost:15672 (guest / guest)

Признак, что цепочка жива:

```bash
docker compose logs -f worker         # «Универсальный воркер запущен»
docker compose logs -f stream-worker  # «Стриминг-воркер запущен»
```

## Состав

| Сервис | Что делает |
|---|---|
| `api` | FastAPI: приём файлов, websocket, выдача результатов |
| `worker` | разбирает очередь RabbitMQ, считает файл целиком |
| `stream-worker` | потоковый режим через Redis pub/sub |
| `rabbitmq` | очередь заданий |
| `redis` | результаты и потоковый обмен |

## Связь с сервисом аутентификации

Пользователей и выдачи токенов здесь нет — этим занимается отдельный проект.
Здесь только проверка подписи.

**Обязательное условие ровно одно: `JWT_SECRET_KEY` должен совпадать** в
`.env` обоих проектов. Больше ничего не нужно — во время работы сервисы друг
к другу не обращаются, и аудио-сервис работает, даже если сервис
аутентификации выключен.

Роль берётся из claim `role` в самом токене, значения `USER`, `SERVICE`,
`ADMIN`. Эндпоинты приёма аудио требуют `SERVICE` или `ADMIN`.

Проверка сквозного сценария:

```bash
# логин в сервисе аутентификации (по умолчанию порт 8001)
TOKEN=$(curl -s -X POST http://localhost:8001/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","password":"demo"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# запрос в аудио-сервис
curl -X POST http://localhost:8000/audio/detect \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@запись.wav" -F "model=pytorch"
```

### Необязательно: отзыв токенов при выходе

По умолчанию токен принимается до истечения срока: выход пользователя в
сервисе аутентификации на уже выданные токены не влияет. Для `SERVICE` это
окно длиной в сутки.

Чтобы выход отзывал токены, нужно дать аудио-сервису доступ к Redis сервиса
аутентификации:

```bash
docker network ls | grep auth        # имя сети, обычно auth-service_default
```

В `.env`:

```
AUTH_REDIS_HOST=auth-redis
AUTH_NETWORK=auth-service_default
```

Запуск с надстройкой:

```bash
docker compose -f docker-compose.yml -f docker-compose.auth-link.yml up -d
```

Плата — появляется связь во время работы: если Redis аутентификации
недоступен, проверка выхода тихо пропускается, а запрос обрабатывается.

## Что изменилось при отделении аутентификации

- Удалены `routes/auth.py`, `services/auth_service.py`, `user_operations/`,
  `database/` — вместе с таблицей пользователей. Своей базы у сервиса больше
  нет, и возня SQLite с потоками ушла вместе с ней.
- Появился `services/token_service.py`: проверка подписи и чтение роли из
  claims, без обращения к базе.
- Лимитер запросов переехал в `routes/audio.py` — он остался единственным его
  потребителем. Правила прежние: 120 запросов в минуту для `SERVICE`,
  10 для остальных.
- Из `requirements.txt` убраны sqlalchemy, passlib, argon2-cffi, pymongo,
  motor, email-validator. `authx` остался — им проверяется подпись.

## Известные особенности

- **Регистрация выдаёт ADMIN.** Это в сервисе аутентификации, но касается и
  нас: любой зарегистрировавшийся проходит проверку прав. Стоит поправить
  там до сдачи.
- **Лимитер в памяти процесса.** При нескольких копиях `api` счётчики
  разойдутся — тогда переносить в Redis.
- **Смена роли отложена** до истечения токена, если не включена надстройка
  с отзывом.
