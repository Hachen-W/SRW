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

// --- учётные данные сеанса ---
//
// Задаются в окне входа. Пока пользователь не вошёл, берутся из config —
// так приложение работает и без окна входа, как раньше.

QString sessionUsername();
QString sessionPassword();
QString sessionRole();      // роль из последнего успешного входа
bool isSignedIn();
void setSession(const QString &username, const QString &password,
                const QString &role);
void clearSession();

// Роль из полезной нагрузки токена. Пустая строка, если разобрать не вышло.
QString roleFromToken(const QString &token);

// Регистрация нового пользователя. Роль назначается сервисом.
bool registerUser(const QString &username, const QString &email,
                  const QString &password, QString *error);

// Проверка пары логин-пароль. При успехе возвращает роль через role.
bool signIn(const QString &username, const QString &password, QString *role,
            QString *error);

class Client {
public:
    Client(const QString &baseUrl = config::baseUrl(),
           const QString &authUrl = config::authUrl(),
           const QString &username = sessionUsername(),
           const QString &password = sessionPassword());

    // Полный цикл через очередь: отправить и дождаться вердикта.
    QJsonObject analyze(const QString &path, const QString &model,
                        double poll, double timeout, double retry,
                        QString *error);

    // Потоковый режим через websocket: возвращает кривую по всему файлу.
    analysis::Curve streamScores(const analysis::Signal &signal,
                                 const QString &model, double chunkSeconds,
                                 double idle, double timeout, QString *error);

    // Открытый вход: нужен окну входа, чтобы проверить пару логин-пароль
    bool login(QString *error);
    QString token() const { return m_token; }

private:
    QString detect(const QString &path, const QString &model, double retry,
                   QString *error);
    QJsonObject waitResult(const QString &requestId, double poll,
                           double timeout, double retry, QString *error);

    QString m_baseUrl;      // аудио-сервис
    QString m_authUrl;      // сервис аутентификации
    QString m_username;
    QString m_password;
    QString m_token;
};

}  // namespace service
