#include "service.h"

#include <QDir>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFile>
#include <QFileInfo>
#include <QHttpMultiPart>
#include <QHttpPart>
#include <QJsonDocument>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QProcess>
#include <QStandardPaths>
#include <QTemporaryFile>
#include <QThread>
#include <QTimer>
#include <QUrl>
#include <QWebSocket>

#include <cmath>

namespace service {
namespace {

const QStringList ServiceExtensions = {"wav", "mp3", "aac", "flac", "ogg"};

// Ждёт завершения ответа, не блокируя цикл событий потока.
void waitForReply(QNetworkReply *reply, int timeoutMs) {
    QEventLoop loop;
    QTimer timer;
    timer.setSingleShot(true);
    QObject::connect(&timer, &QTimer::timeout, &loop, &QEventLoop::quit);
    QObject::connect(reply, &QNetworkReply::finished, &loop, &QEventLoop::quit);
    timer.start(timeoutMs);
    loop.exec();
}

int statusOf(QNetworkReply *reply) {
    return reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
}

// Простой фильтр нижних частот перед понижением частоты дискретизации,
// иначе высокие составляющие завернутся в слышимый диапазон.
QVector<double> lowPass(const QVector<double> &input, double cutoffShare) {
    const int taps = 31;
    QVector<double> kernel(taps);
    double sum = 0.0;
    for (int i = 0; i < taps; ++i) {
        const double n = i - (taps - 1) / 2.0;
        const double sinc =
            n == 0.0 ? 2.0 * cutoffShare
                     : std::sin(2.0 * M_PI * cutoffShare * n) / (M_PI * n);
        const double window =
            0.54 - 0.46 * std::cos(2.0 * M_PI * i / (taps - 1));
        kernel[i] = sinc * window;
        sum += kernel[i];
    }
    for (double &value : kernel) {
        value /= sum;
    }

    QVector<double> output(input.size(), 0.0);
    const int half = (taps - 1) / 2;
    for (int i = 0; i < input.size(); ++i) {
        double accumulator = 0.0;
        for (int k = 0; k < taps; ++k) {
            const int index = i + k - half;
            if (index >= 0 && index < input.size()) {
                accumulator += input[index] * kernel[k];
            }
        }
        output[i] = accumulator;
    }
    return output;
}

}  // namespace

bool isServiceExtension(const QString &path) {
    return ServiceExtensions.contains(QFileInfo(path).suffix().toLower());
}

QString prepareForService(const QString &path, bool *temporary,
                          QString *error) {
    // Форматы из списка уходят как есть — без пересжатия и без изменения
    // частоты, чтобы модель получила ровно исходный сигнал.
    if (isServiceExtension(path)) {
        *temporary = false;
        return path;
    }

    const QString exe = analysis::ffmpegBin();
    if (exe.isEmpty()) {
        if (error) {
            *error = QStringLiteral(
                "Сервис не принимает этот формат, а ffmpeg не найден");
        }
        return {};
    }

    QTemporaryFile temp(QDir::tempPath() + "/af-send-XXXXXX.wav");
    temp.setAutoRemove(false);
    if (!temp.open()) {
        if (error) {
            *error = QStringLiteral("Не удалось создать временный файл");
        }
        return {};
    }
    const QString outPath = temp.fileName();
    temp.close();

    QProcess process;
    process.start(exe, {"-v", "quiet", "-y", "-i", path, "-acodec",
                        "pcm_s16le", "-vn", outPath});
    process.waitForFinished(-1);
    if (process.exitCode() != 0) {
        QFile::remove(outPath);
        if (error) {
            *error = QStringLiteral("ffmpeg не смог подготовить файл");
        }
        return {};
    }
    *temporary = true;
    return outPath;
}

QByteArray toPcm16(const analysis::Signal &signal) {
    QVector<double> samples = signal.samples;
    if (signal.sampleRate != config::StreamSampleRate) {
        const double ratio = double(config::StreamSampleRate) / signal.sampleRate;
        if (ratio < 1.0) {
            samples = lowPass(samples, ratio / 2.0);
        }
        const int count = int(samples.size() * ratio);
        QVector<double> resampled(count);
        for (int i = 0; i < count; ++i) {
            const double position = i / ratio;
            const int index = int(position);
            const double fraction = position - index;
            const double left = samples[std::min<int>(index, samples.size() - 1)];
            const double right =
                samples[std::min<int>(index + 1, samples.size() - 1)];
            resampled[i] = left + (right - left) * fraction;
        }
        samples = resampled;
    }

    QByteArray data;
    data.resize(samples.size() * 2);
    char *raw = data.data();
    for (int i = 0; i < samples.size(); ++i) {
        const qint16 value = qint16(std::clamp(samples[i], -1.0, 1.0) * 32767);
        raw[i * 2] = char(value & 0xFF);
        raw[i * 2 + 1] = char((value >> 8) & 0xFF);
    }
    return data;
}

Client::Client(const QString &baseUrl, const QString &username,
               const QString &password)
    : m_baseUrl(baseUrl), m_username(username), m_password(password) {
    while (m_baseUrl.endsWith('/')) {
        m_baseUrl.chop(1);
    }
}

bool Client::login(QString *error) {
    QNetworkAccessManager manager;
    QNetworkRequest request(QUrl(m_baseUrl + "/auth/login"));
    request.setHeader(QNetworkRequest::ContentTypeHeader, "application/json");

    QJsonObject body;
    body["username"] = m_username;
    body["password"] = m_password;

    QNetworkReply *reply =
        manager.post(request, QJsonDocument(body).toJson());
    waitForReply(reply, 10000);

    const int status = statusOf(reply);
    const QByteArray answer = reply->readAll();
    reply->deleteLater();

    if (status == 401) {
        if (error) {
            *error = QStringLiteral("Неверный логин или пароль");
        }
        return false;
    }
    if (status != 200) {
        if (error) {
            *error = QStringLiteral("Логин не удался, код %1").arg(status);
        }
        return false;
    }
    m_token = QJsonDocument::fromJson(answer).object()
                  .value("access_token").toString();
    return !m_token.isEmpty();
}

QString Client::detect(const QString &path, const QString &model, double retry,
                       QString *error) {
    for (int attempt = 0; attempt < 3; ++attempt) {
        if (m_token.isEmpty() && !login(error)) {
            return {};
        }

        QFile *file = new QFile(path);
        if (!file->open(QIODevice::ReadOnly)) {
            delete file;
            if (error) {
                *error = QStringLiteral("Не удалось открыть файл");
            }
            return {};
        }

        QHttpMultiPart *multiPart =
            new QHttpMultiPart(QHttpMultiPart::FormDataType);

        QHttpPart filePart;
        filePart.setHeader(QNetworkRequest::ContentDispositionHeader,
                           QVariant(QStringLiteral(
                                        "form-data; name=\"file\"; filename=\"%1\"")
                                        .arg(QFileInfo(path).fileName())));
        filePart.setBodyDevice(file);
        file->setParent(multiPart);
        multiPart->append(filePart);

        QHttpPart modelPart;
        modelPart.setHeader(QNetworkRequest::ContentDispositionHeader,
                            QVariant("form-data; name=\"model\""));
        modelPart.setBody(model.toUtf8());
        multiPart->append(modelPart);

        QNetworkAccessManager manager;
        QNetworkRequest request(QUrl(m_baseUrl + "/audio/detect"));
        request.setRawHeader("Authorization", ("Bearer " + m_token).toUtf8());

        QNetworkReply *reply = manager.post(request, multiPart);
        multiPart->setParent(reply);
        waitForReply(reply, 60000);

        const int status = statusOf(reply);
        const QByteArray answer = reply->readAll();
        reply->deleteLater();

        if (status == 401) {
            m_token.clear();          // токен протух
            continue;
        }
        if (status == 429) {
            QThread::msleep(int(retry * 1000));   // лимит запросов исчерпан
            continue;
        }
        if (status == 403) {
            if (error) {
                *error = QStringLiteral("Нужна роль SERVICE или ADMIN");
            }
            return {};
        }
        if (status == 413) {
            if (error) {
                *error = QStringLiteral(
                    "Файл больше лимита сервиса. Поднимите MAX_FILE_SIZE_MB "
                    "в docker-compose и перезапустите api");
            }
            return {};
        }
        if (status != 200 && status != 202) {
            if (error) {
                *error = QStringLiteral("Сервис ответил кодом %1").arg(status);
            }
            return {};
        }
        return QJsonDocument::fromJson(answer).object()
            .value("request_id").toString();
    }
    if (error) {
        *error = QStringLiteral("Сервис не принял файл");
    }
    return {};
}

QJsonObject Client::waitResult(const QString &requestId, double poll,
                               double timeout, double retry, QString *error) {
    QElapsedTimer clock;
    clock.start();

    while (clock.elapsed() / 1000.0 < timeout) {
        if (m_token.isEmpty() && !login(error)) {
            return {};
        }

        QNetworkAccessManager manager;
        QNetworkRequest request(
            QUrl(m_baseUrl + "/audio/result/" + requestId));
        request.setRawHeader("Authorization", ("Bearer " + m_token).toUtf8());

        QNetworkReply *reply = manager.get(request);
        waitForReply(reply, 10000);

        const int status = statusOf(reply);
        const QByteArray answer = reply->readAll();
        reply->deleteLater();

        if (status == 401) {
            m_token.clear();
            continue;
        }
        if (status == 429) {
            // Роли USER и ADMIN дают 10 запросов в минуту, ждём окно
            QThread::msleep(int(retry * 1000));
            continue;
        }
        if (status != 200) {
            if (error) {
                *error = QStringLiteral("Сервис ответил кодом %1").arg(status);
            }
            return {};
        }

        const QJsonObject data = QJsonDocument::fromJson(answer).object();
        if (data.value("status").toString() != "processing") {
            return data;
        }
        QThread::msleep(int(poll * 1000));
    }

    if (error) {
        *error = QStringLiteral("Сервис не ответил за отведённое время");
    }
    return {};
}

QJsonObject Client::analyze(const QString &path, const QString &model,
                            double poll, double timeout, double retry,
                            QString *error) {
    bool temporary = false;
    const QString sendPath = prepareForService(path, &temporary, error);
    if (sendPath.isEmpty()) {
        return {};
    }

    const QString requestId = detect(sendPath, model, retry, error);
    QJsonObject result;
    if (!requestId.isEmpty()) {
        result = waitResult(requestId, poll, timeout, retry, error);
    }
    if (temporary) {
        QFile::remove(sendPath);
    }
    return result;
}

analysis::Curve Client::streamScores(const analysis::Signal &signal,
                                     const QString &model, double chunkSeconds,
                                     double idle, double timeout,
                                     QString *error) {
    analysis::Curve curve;
    if (m_token.isEmpty() && !login(error)) {
        return curve;
    }

    QString url = m_baseUrl;
    url.replace("https://", "wss://");
    url.replace("http://", "ws://");
    url += QStringLiteral("/audio/stream?token=%1&model=%2").arg(m_token, model);

    QWebSocket socket;
    QEventLoop connectLoop;
    bool connected = false;
    QObject::connect(&socket, &QWebSocket::connected, &connectLoop,
                     [&connected, &connectLoop]() {
                         connected = true;
                         connectLoop.quit();
                     });
    QObject::connect(&socket,
                     QOverload<QAbstractSocket::SocketError>::of(
                         &QWebSocket::error),
                     &connectLoop,
                     [&connectLoop](QAbstractSocket::SocketError) {
                         connectLoop.quit();
                     });
    QTimer::singleShot(15000, &connectLoop, &QEventLoop::quit);
    socket.open(QUrl(url));
    connectLoop.exec();

    if (!connected) {
        if (error) {
            *error = QStringLiteral("Websocket не подключился: %1")
                         .arg(socket.errorString());
        }
        return curve;
    }

    bool terminated = false;
    QElapsedTimer sinceAnswer;
    sinceAnswer.start();

    // Позицию сообщает воркер: он может сильно отставать от отправки
    QObject::connect(&socket, &QWebSocket::textMessageReceived, &socket,
                     [&](const QString &message) {
                         const QJsonObject data =
                             QJsonDocument::fromJson(message.toUtf8()).object();
                         curve.times.append(data.value("position").toDouble());
                         curve.probs.append(
                             data.value("current_score").toDouble());
                         sinceAnswer.restart();
                         if (data.value("status").toString() == "terminated") {
                             terminated = true;
                         }
                     });

    const QByteArray pcm = toPcm16(signal);
    const int step = int(config::StreamSampleRate * chunkSeconds) * 2;

    for (int start = 0; start < pcm.size() && !terminated; start += step) {
        socket.sendBinaryMessage(pcm.mid(start, step));
        QEventLoop pump;
        QTimer::singleShot(50, &pump, &QEventLoop::quit);
        pump.exec();      // даём прийти ответам, накопившимся за это время
    }

    // Медленные модели отвечают заметно позже, чем мы отправили звук,
    // поэтому ждём, пока ответы не перестанут приходить.
    QElapsedTimer total;
    total.start();
    while (!terminated && total.elapsed() / 1000.0 < timeout
           && sinceAnswer.elapsed() / 1000.0 < idle) {
        QEventLoop pump;
        QTimer::singleShot(200, &pump, &QEventLoop::quit);
        pump.exec();
    }

    socket.close();
    return curve;
}

}  // namespace service
