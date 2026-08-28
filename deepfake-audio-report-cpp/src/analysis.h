// Аналитическое ядро: чтение файлов, спектрограмма, детекторы, проверки.
#pragma once

#include <QString>
#include <QVector>

namespace analysis {

// Сигнал: моно, значения примерно в диапазоне -1..1
struct Signal {
    QVector<double> samples;
    int sampleRate = 0;
    double duration() const {
        return sampleRate > 0 ? double(samples.size()) / sampleRate : 0.0;
    }
};

// Сведения о контейнере и кодеке для отчёта
struct FormatInfo {
    QString container;
    QString codec;
    int sampleRate = 0;
    int channels = 0;
    QString bitRate;
    bool lossy = false;
    bool valid = false;
};

// Одна звуковая дорожка файла
struct AudioStream {
    int index = 0;
    QString codec;
    int channels = 0;
    int sampleRate = 0;
    QString language;
};

// Спектрограмма в дБ: power[частота][кадр]
struct Spectrogram {
    QVector<QVector<double>> power;
    QVector<double> freqs;
    QVector<double> times;
};

// Кривая оценок во времени
struct Curve {
    QVector<double> times;
    QVector<double> probs;
};

struct Interval {
    double start = 0.0;
    double end = 0.0;
};

// Классические признаки обработки
struct ClassicChecks {
    double dcOffset = 0.0;
    double cutoffHz = 0.0;
    QVector<Interval> constantRuns;
    int repeatPairs = 0;
};

// --- внешние инструменты ---
QString ffmpegBin(const QString &name = QStringLiteral("ffmpeg"));

// --- чтение файлов ---
FormatInfo probeFormat(const QString &path);
QVector<AudioStream> listAudioStreams(const QString &path);
bool isVideo(const QString &path);
// Достаёт дорожку из видео без перекодирования. Возвращает путь к временному
// файлу — удалять его должен вызывающий.
QString extractAudio(const QString &path, int index, QString *error = nullptr);
Signal loadAudio(const QString &path, QString *error = nullptr);

// --- спектрограмма ---
Spectrogram spectrogramDb(const Signal &signal, double dynamicRange = 100.0,
                          int nfft = 512);

// --- детектирование ---
double baselineScore(const double *segment, int length, int sampleRate);
Curve frameProbabilities(const Signal &signal, double window, double hop);
QVector<Interval> intervalsAbove(const Curve &curve, double threshold);

// --- классические проверки ---
ClassicChecks classicChecks(const Signal &signal);

}  // namespace analysis
