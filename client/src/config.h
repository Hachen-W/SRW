// Все настройки приложения в одном месте.
#pragma once

#include <QString>

// Настройки берутся из переменных окружения, если они заданы: так один и тот же
// бинарник работает и на хосте, и в контейнере, где сервис живёт по другому адресу.
namespace config {

inline QString fromEnvironment(const char *name, const QString &fallback) {
    const QString value = qEnvironmentVariable(name);
    return value.isEmpty() ? fallback : value;
}

// --- анализ ---
inline const QString ModelPath = QStringLiteral("model.onnx");
inline constexpr double Threshold = 0.7;   // порог подозрительного участка
inline constexpr double Window = 2.0;      // длина окна анализа, с
inline constexpr double Hop = 0.5;         // шаг окна, с

// --- сервисы ---
// Пароль лежит прямо здесь — так удобнее для демо, но в общий репозиторий
// такой файл коммитить не стоит.
inline QString baseUrl() {          // аудио-сервис: анализ
    return fromEnvironment("SRW_URL", QStringLiteral("http://localhost:8000"));
}
inline QString authUrl() {          // сервис аутентификации: логин
    return fromEnvironment("AUTH_URL", QStringLiteral("http://localhost:8001"));
}
inline QString username() {
    return fromEnvironment("SRW_USER", QStringLiteral("demo"));
}
// Заданы ли учётные данные в окружении. Если да, окно входа можно не
// открывать: это осознанная настройка запуска, а не значение по умолчанию.
inline bool hasEnvironmentCredentials() {
    return qEnvironmentVariableIsSet("SRW_USER")
           && qEnvironmentVariableIsSet("SRW_PASSWORD");
}
inline QString password() {
    return fromEnvironment("SRW_PASSWORD", QStringLiteral("demo"));
}

// Сервер лимитирует: 10 запросов в минуту для ADMIN и USER, 120 для SERVICE.
inline constexpr double PollInterval = 6.0;    // пауза между опросами, с
inline constexpr double RetryPause = 15.0;     // пауза после 429, с
inline constexpr double ResultTimeout = 180.0; // сколько ждём вердикт, с

// Модель на сервере по умолчанию: pytorch или pyara
inline const QString DefaultModel = QStringLiteral("pytorch");

// Потоковый режим: воркер ждёт 16 кГц моно int16.
inline constexpr int StreamSampleRate = 16000;
inline constexpr double ChunkSeconds = 0.5;
inline constexpr double StreamTimeout = 300.0; // общий таймаут потока, с
inline constexpr double StreamIdle = 20.0;     // ожидание тишины, с

}  // namespace config
