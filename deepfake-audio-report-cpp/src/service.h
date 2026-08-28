// Клиент к сервису SRW: логин, отправка файла, ожидание результата.
//
// Все методы синхронные — их вызывают из фонового потока, а ожидание ответа
// сделано через локальный цикл событий.
#pragma once

#include <QJsonObject>
#include <QString>

#include "analysis.h"
#include "config.h"

namespace service {

// Сервис принимает только эти расширения (ALLOWED_EXTENSIONS в routes/audio.py)
bool isServiceExtension(const QString &path);

// Готовит файл к отправке. temporary=true — файл нужно удалить после отправки.
QString prepareForService(const QString &path, bool *temporary,
                          QString *error = nullptr);

// Приводит сигнал к 16 кГц моно int16 — в таком виде его ждёт воркер.
QByteArray toPcm16(const analysis::Signal &signal);

class Client {
public:
    Client(const QString &baseUrl = config::BaseUrl,
           const QString &username = config::Username,
           const QString &password = config::Password);

    // Полный цикл через очередь: отправить и дождаться вердикта.
    QJsonObject analyze(const QString &path, const QString &model,
                        double poll, double timeout, double retry,
                        QString *error);

    // Потоковый режим через websocket: возвращает кривую по всему файлу.
    analysis::Curve streamScores(const analysis::Signal &signal,
                                 const QString &model, double chunkSeconds,
                                 double idle, double timeout, QString *error);

private:
    bool login(QString *error);
    QString detect(const QString &path, const QString &model, double retry,
                   QString *error);
    QJsonObject waitResult(const QString &requestId, double poll,
                           double timeout, double retry, QString *error);

    QString m_baseUrl;
    QString m_username;
    QString m_password;
    QString m_token;
};

}  // namespace service
