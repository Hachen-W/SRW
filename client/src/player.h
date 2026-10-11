// Воспроизведение фонограммы внешним проигрывателем.
//
// Свой звуковой вывод не используем: отдельный процесс не может уронить
// приложение, а ffplay уже стоит вместе с ffmpeg.
#pragma once

#include <QElapsedTimer>
#include <QString>

#include "analysis.h"

class QProcess;

class Player {
public:
    Player() = default;
    ~Player();

    bool play(const analysis::Signal &signal, QString *error = nullptr);
    void stop();
    bool isPlaying() const;
    double position() const;   // секунды с начала записи

private:
    QProcess *m_process = nullptr;
    QString m_tempPath;
    QElapsedTimer m_timer;
    double m_duration = 0.0;
};
