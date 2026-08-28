#include "player.h"

#include <QDataStream>
#include <QDir>
#include <QFile>
#include <QProcess>
#include <QStandardPaths>
#include <QTemporaryFile>

#include <cmath>

namespace {

// Пишет сигнал во временный wav: моно, 16 бит.
bool writeWav(const QString &path, const analysis::Signal &signal) {
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly)) {
        return false;
    }
    QDataStream stream(&file);
    stream.setByteOrder(QDataStream::LittleEndian);

    const int count = signal.samples.size();
    const int dataSize = count * 2;

    file.write("RIFF");
    stream << quint32(36 + dataSize);
    file.write("WAVEfmt ");
    stream << quint32(16) << quint16(1) << quint16(1)
           << quint32(signal.sampleRate)
           << quint32(signal.sampleRate * 2) << quint16(2) << quint16(16);
    file.write("data");
    stream << quint32(dataSize);

    for (double value : signal.samples) {
        const double clamped = std::clamp(value, -1.0, 1.0);
        stream << qint16(clamped * 32767);
    }
    file.close();
    return true;
}

}  // namespace

Player::~Player() {
    stop();
}

bool Player::play(const analysis::Signal &signal, QString *error) {
    stop();

    QString binary = QStandardPaths::findExecutable("ffplay");
    if (binary.isEmpty()) {
        binary = QStandardPaths::findExecutable("aplay");
    }
    if (binary.isEmpty()) {
        if (error) {
            *error = QStringLiteral("Не найден ffplay или aplay");
        }
        return false;
    }

    QTemporaryFile temp(QDir::tempPath() + "/af-play-XXXXXX.wav");
    temp.setAutoRemove(false);
    if (!temp.open()) {
        if (error) {
            *error = QStringLiteral("Не удалось создать временный файл");
        }
        return false;
    }
    m_tempPath = temp.fileName();
    temp.close();

    if (!writeWav(m_tempPath, signal)) {
        if (error) {
            *error = QStringLiteral("Не удалось записать временный wav");
        }
        return false;
    }

    QStringList arguments;
    if (binary.endsWith("ffplay")) {
        arguments << "-hide_banner" << "-loglevel" << "quiet" << "-nodisp"
                  << "-autoexit" << m_tempPath;
    } else {
        arguments << "-q" << m_tempPath;
    }

    m_process = new QProcess();
    m_process->start(binary, arguments);
    if (!m_process->waitForStarted(3000)) {
        if (error) {
            *error = QStringLiteral("Проигрыватель не запустился");
        }
        stop();
        return false;
    }
    m_timer.start();
    m_duration = signal.duration();
    return true;
}

void Player::stop() {
    if (m_process) {
        if (m_process->state() != QProcess::NotRunning) {
            m_process->terminate();
            if (!m_process->waitForFinished(2000)) {
                m_process->kill();
                m_process->waitForFinished(1000);
            }
        }
        delete m_process;
        m_process = nullptr;
    }
    if (!m_tempPath.isEmpty()) {
        QFile::remove(m_tempPath);
        m_tempPath.clear();
    }
}

bool Player::isPlaying() const {
    return m_process && m_process->state() != QProcess::NotRunning;
}

double Player::position() const {
    if (!m_process) {
        return 0.0;
    }
    return std::min(m_timer.elapsed() / 1000.0, m_duration);
}
