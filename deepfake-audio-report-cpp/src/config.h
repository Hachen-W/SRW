// Все настройки приложения в одном месте.
#pragma once

#include <QString>

namespace config {

// --- анализ ---
inline const QString ModelPath = QStringLiteral("model.onnx");
inline constexpr double Threshold = 0.7;   // порог подозрительного участка
inline constexpr double Window = 2.0;      // длина окна анализа, с
inline constexpr double Hop = 0.5;         // шаг окна, с

// --- сервис SRW ---
// Пароль лежит прямо здесь — так удобнее для демо, но в общий репозиторий
// такой файл коммитить не стоит.
inline const QString BaseUrl = QStringLiteral("http://localhost:8000");
inline const QString Username = QStringLiteral("demo");
inline const QString Password = QStringLiteral("demo");

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
