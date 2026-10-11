#include "analysis.h"

#include <QDir>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QSet>
#include <QStandardPaths>
#include <QTemporaryFile>

#include <cmath>
#include <complex>

namespace analysis {
namespace {

// Кодеки со сжатием с потерями. Для них часть проверок неинформативна.
const QSet<QString> LossyCodecs = {
    "mp3", "aac", "wmav1", "wmav2", "vorbis", "opus",
    "amr_nb", "amr_wb", "gsm", "ac3", "atrac3"};

// Запускает программу и возвращает её вывод. ok=false, если код возврата не 0.
QByteArray runProcess(const QString &program, const QStringList &arguments,
                      bool *ok = nullptr) {
    QProcess process;
    process.start(program, arguments);
    process.waitForFinished(-1);
    if (ok) {
        *ok = process.exitStatus() == QProcess::NormalExit
              && process.exitCode() == 0;
    }
    return process.readAllStandardOutput();
}

QJsonObject probeStreams(const QString &path) {
    const QString exe = ffmpegBin(QStringLiteral("ffprobe"));
    if (exe.isEmpty()) {
        return {};
    }
    bool ok = false;
    const QByteArray out = runProcess(
        exe, {"-v", "quiet", "-print_format", "json", "-show_format",
              "-show_streams", path}, &ok);
    if (!ok) {
        return {};
    }
    return QJsonDocument::fromJson(out).object();
}

int nextPowerOfTwo(int value) {
    int result = 1;
    while (result < value) {
        result *= 2;
    }
    return result;
}

// Быстрое преобразование Фурье по основанию 2, на месте.
void fft(QVector<std::complex<double>> &data) {
    const int n = data.size();
    for (int i = 1, j = 0; i < n; ++i) {
        int bit = n >> 1;
        for (; j & bit; bit >>= 1) {
            j ^= bit;
        }
        j ^= bit;
        if (i < j) {
            std::swap(data[i], data[j]);
        }
    }
    for (int length = 2; length <= n; length <<= 1) {
        const double angle = -2.0 * M_PI / length;
        const std::complex<double> step(std::cos(angle), std::sin(angle));
        for (int i = 0; i < n; i += length) {
            std::complex<double> factor(1.0, 0.0);
            for (int j = 0; j < length / 2; ++j) {
                const std::complex<double> u = data[i + j];
                const std::complex<double> v = data[i + j + length / 2] * factor;
                data[i + j] = u + v;
                data[i + j + length / 2] = u - v;
                factor *= step;
            }
        }
    }
}

// Модули спектра для действительного сигнала. Длина дополняется нулями до
// степени двойки, поэтому шаг по частоте равен sampleRate / paddedLength.
QVector<double> spectrumMagnitudes(const double *values, int length,
                                   int *paddedLength = nullptr) {
    const int size = nextPowerOfTwo(length);
    QVector<std::complex<double>> buffer(size, std::complex<double>(0.0, 0.0));
    for (int i = 0; i < length; ++i) {
        buffer[i] = std::complex<double>(values[i], 0.0);
    }
    fft(buffer);
    if (paddedLength) {
        *paddedLength = size;
    }
    QVector<double> result(size / 2 + 1);
    for (int i = 0; i < result.size(); ++i) {
        result[i] = std::abs(buffer[i]);
    }
    return result;
}

}  // namespace

QString ffmpegBin(const QString &name) {
    return QStandardPaths::findExecutable(name);
}

FormatInfo probeFormat(const QString &path) {
    const QJsonObject root = probeStreams(path);
    if (root.isEmpty()) {
        return {};
    }
    for (const QJsonValue &value : root.value("streams").toArray()) {
        const QJsonObject stream = value.toObject();
        if (stream.value("codec_type").toString() != "audio") {
            continue;
        }
        FormatInfo info;
        info.codec = stream.value("codec_name").toString();
        info.sampleRate = stream.value("sample_rate").toString().toInt();
        info.channels = stream.value("channels").toInt();
        info.container = root.value("format").toObject()
                             .value("format_name").toString();
        info.bitRate = root.value("format").toObject()
                           .value("bit_rate").toString();
        info.lossy = LossyCodecs.contains(info.codec);
        info.valid = true;
        return info;
    }
    return {};
}

QVector<AudioStream> listAudioStreams(const QString &path) {
    QVector<AudioStream> streams;
    const QJsonObject root = probeStreams(path);
    for (const QJsonValue &value : root.value("streams").toArray()) {
        const QJsonObject stream = value.toObject();
        if (stream.value("codec_type").toString() != "audio") {
            continue;
        }
        AudioStream item;
        item.index = streams.size();
        item.codec = stream.value("codec_name").toString();
        item.channels = stream.value("channels").toInt();
        item.sampleRate = stream.value("sample_rate").toString().toInt();
        item.language = stream.value("tags").toObject()
                            .value("language").toString();
        streams.append(item);
    }
    return streams;
}

bool isVideo(const QString &path) {
    const QJsonObject root = probeStreams(path);
    for (const QJsonValue &value : root.value("streams").toArray()) {
        const QJsonObject stream = value.toObject();
        const QString codec = stream.value("codec_name").toString();
        // Обложки в mp3 тоже идут видеопотоком, их не считаем
        if (stream.value("codec_type").toString() == "video"
            && codec != "mjpeg" && codec != "png" && codec != "bmp") {
            return true;
        }
    }
    return false;
}

QString extractAudio(const QString &path, int index, QString *error) {
    const QString exe = ffmpegBin();
    if (exe.isEmpty()) {
        if (error) {
            *error = QStringLiteral("Для извлечения звука нужен ffmpeg");
        }
        return {};
    }

    QTemporaryFile temp(QDir::tempPath() + "/af-XXXXXX.mka");
    temp.setAutoRemove(false);
    if (!temp.open()) {
        if (error) {
            *error = QStringLiteral("Не удалось создать временный файл");
        }
        return {};
    }
    const QString outPath = temp.fileName();
    temp.close();

    const QString map = QStringLiteral("0:a:%1").arg(index);
    // Поток копируется как есть, чтобы не добавить своих артефактов
    bool ok = false;
    runProcess(exe, {"-v", "quiet", "-y", "-i", path, "-map", map,
                     "-acodec", "copy", "-vn", outPath}, &ok);
    if (!ok || QFileInfo(outPath).size() == 0) {
        // Некоторые кодеки не ложатся в контейнер — тогда декодируем
        runProcess(exe, {"-v", "quiet", "-y", "-i", path, "-map", map,
                         "-acodec", "pcm_s16le", "-vn", outPath}, &ok);
    }
    if (!ok) {
        QFile::remove(outPath);
        if (error) {
            *error = QStringLiteral("ffmpeg не смог извлечь дорожку");
        }
        return {};
    }
    return outPath;
}

Signal loadAudio(const QString &path, QString *error) {
    const QString exe = ffmpegBin();
    if (exe.isEmpty()) {
        if (error) {
            *error = QStringLiteral("Файл не прочитан: не найден ffmpeg");
        }
        return {};
    }

    const FormatInfo info = probeFormat(path);
    const int sampleRate = info.sampleRate > 0 ? info.sampleRate : 44100;

    bool ok = false;
    const QByteArray raw = runProcess(
        exe, {"-v", "quiet", "-i", path, "-f", "f32le", "-ac", "1",
              "-ar", QString::number(sampleRate), "-"}, &ok);
    if (!ok || raw.isEmpty()) {
        if (error) {
            *error = QStringLiteral("Не удалось декодировать файл");
        }
        return {};
    }

    Signal signal;
    signal.sampleRate = sampleRate;
    const int count = raw.size() / int(sizeof(float));
    const float *values = reinterpret_cast<const float *>(raw.constData());
    signal.samples.resize(count);
    for (int i = 0; i < count; ++i) {
        signal.samples[i] = double(values[i]);
    }
    return signal;
}

Spectrogram spectrogramDb(const Signal &signal, double dynamicRange, int nfft) {
    Spectrogram result;
    if (signal.samples.isEmpty() || signal.sampleRate <= 0) {
        return result;
    }

    QVector<double> samples = signal.samples;
    if (samples.size() < nfft) {
        samples.resize(nfft);   // короткий сигнал дополняем нулями
    }

    const int step = nfft / 2;
    const int frameCount = 1 + (samples.size() - nfft) / step;
    const int bins = nfft / 2 + 1;

    QVector<double> window(nfft);
    for (int i = 0; i < nfft; ++i) {
        window[i] = 0.5 - 0.5 * std::cos(2.0 * M_PI * i / (nfft - 1));
    }

    // power[частота][кадр]
    result.power.resize(bins);
    for (int bin = 0; bin < bins; ++bin) {
        result.power[bin].resize(frameCount);
    }

    double top = 0.0;
    QVector<double> segment(nfft);
    for (int frame = 0; frame < frameCount; ++frame) {
        const int offset = frame * step;
        for (int i = 0; i < nfft; ++i) {
            segment[i] = samples[offset + i] * window[i];
        }
        const QVector<double> magnitudes =
            spectrumMagnitudes(segment.constData(), nfft);
        for (int bin = 0; bin < bins; ++bin) {
            const double value = magnitudes[bin] * magnitudes[bin];
            result.power[bin][frame] = value;
            top = std::max(top, value);
        }
    }

    // Тишина даёт нулевую мощность: вместо логарифма от нуля берём нижнюю
    // границу диапазона — делить на ноль не приходится
    const double floor =
        top > 0.0 ? top * std::pow(10.0, -dynamicRange / 10.0) : 1e-20;
    for (int bin = 0; bin < bins; ++bin) {
        for (int frame = 0; frame < frameCount; ++frame) {
            result.power[bin][frame] =
                10.0 * std::log10(std::max(result.power[bin][frame], floor));
        }
    }

    result.freqs.resize(bins);
    for (int bin = 0; bin < bins; ++bin) {
        result.freqs[bin] = double(bin) * signal.sampleRate / nfft;
    }
    result.times.resize(frameCount);
    for (int frame = 0; frame < frameCount; ++frame) {
        result.times[frame] =
            (frame * step + nfft / 2.0) / signal.sampleRate;
    }
    return result;
}

double baselineScore(const double *segment, int length, int sampleRate) {
    // ЗАГЛУШКА, а не детектор: две простые спектральные характеристики.
    // Числа отсюда нельзя показывать как результат детектирования.
    QVector<double> windowed(length);
    for (int i = 0; i < length; ++i) {
        const double window =
            0.5 - 0.5 * std::cos(2.0 * M_PI * i / (length - 1));
        windowed[i] = segment[i] * window;
    }

    int padded = 0;
    const QVector<double> magnitudes =
        spectrumMagnitudes(windowed.constData(), length, &padded);

    double total = 1e-9;
    double high = 0.0;
    double sum = 0.0;
    double sumSquares = 0.0;
    for (int bin = 0; bin < magnitudes.size(); ++bin) {
        const double frequency = double(bin) * sampleRate / padded;
        total += magnitudes[bin];
        if (frequency > 6000.0) {
            high += magnitudes[bin];
        }
        sum += magnitudes[bin];
        sumSquares += magnitudes[bin] * magnitudes[bin];
    }
    const double count = magnitudes.size();
    const double mean = sum / count;
    const double variance = std::max(sumSquares / count - mean * mean, 0.0);
    const double flat = std::sqrt(variance) / (mean + 1e-9);

    const double score = 0.5 + 0.5 * (0.3 - high / total) - 0.05 * flat;
    return std::clamp(score, 0.0, 1.0);
}

Curve frameProbabilities(const Signal &signal, double window, double hop) {
    Curve curve;
    if (signal.samples.isEmpty() || signal.sampleRate <= 0) {
        return curve;
    }
    const int length = int(window * signal.sampleRate);
    const int step = std::max(int(hop * signal.sampleRate), 1);
    if (length <= 1) {
        return curve;
    }

    for (int start = 0; start + length <= signal.samples.size(); start += step) {
        const double score = baselineScore(signal.samples.constData() + start,
                                           length, signal.sampleRate);
        curve.times.append((start + length / 2.0) / signal.sampleRate);
        curve.probs.append(score);
    }
    return curve;
}

QVector<Interval> intervalsAbove(const Curve &curve, double threshold) {
    QVector<Interval> result;
    bool inside = false;
    double start = 0.0;
    for (int i = 0; i < curve.times.size(); ++i) {
        if (curve.probs[i] >= threshold && !inside) {
            inside = true;
            start = curve.times[i];
        } else if (curve.probs[i] < threshold && inside) {
            inside = false;
            result.append({start, curve.times[i]});
        }
    }
    if (inside && !curve.times.isEmpty()) {
        result.append({start, curve.times.last()});
    }
    return result;
}

ClassicChecks classicChecks(const Signal &signal) {
    ClassicChecks checks;
    if (signal.samples.isEmpty() || signal.sampleRate <= 0) {
        return checks;
    }
    const int sampleRate = signal.sampleRate;
    const QVector<double> &x = signal.samples;

    // Смещение постоянной составляющей
    double sum = 0.0;
    for (double value : x) {
        sum += value;
    }
    checks.dcOffset = sum / x.size();

    // Частота среза спектра: резкий срез ниже Найквиста — признак кодека
    const int limit = std::min(x.size(), qsizetype(sampleRate) * 10);
    int padded = 0;
    const QVector<double> magnitudes =
        spectrumMagnitudes(x.constData(), limit, &padded);
    double energy = 0.0;
    for (double value : magnitudes) {
        energy += value * value;
    }
    double running = 0.0;
    for (int bin = 0; bin < magnitudes.size(); ++bin) {
        running += magnitudes[bin] * magnitudes[bin];
        if (energy > 0.0 && running / energy >= 0.995) {
            checks.cutoffHz = double(bin) * sampleRate / padded;
            break;
        }
    }

    // Участки с постоянным значением отсчётов: дропауты и вставки
    const double minSamples = 0.020 * sampleRate;
    int runStart = -1;
    for (int i = 1; i < x.size(); ++i) {
        const bool same = std::abs(x[i] - x[i - 1]) < 1e-6;
        if (same && runStart < 0) {
            runStart = i - 1;
        } else if (!same && runStart >= 0) {
            if (i - runStart >= minSamples) {
                checks.constantRuns.append(
                    {double(runStart) / sampleRate, double(i) / sampleRate});
            }
            runStart = -1;
        }
    }

    // Повторяющиеся фрагменты по спектральным отпечаткам блоков
    const int block = int(0.5 * sampleRate);
    QVector<QVector<double>> prints;
    for (int start = 0; start + block <= x.size(); start += block) {
        QVector<double> magnitude =
            spectrumMagnitudes(x.constData() + start, block);
        magnitude.resize(std::min(magnitude.size(), qsizetype(256)));
        double norm = 1e-9;
        for (double value : magnitude) {
            norm += value * value;
        }
        norm = std::sqrt(norm);
        for (double &value : magnitude) {
            value /= norm;
        }
        prints.append(magnitude);
    }
    for (int i = 0; i < prints.size(); ++i) {
        for (int j = i + 2; j < prints.size(); ++j) {
            double dot = 0.0;
            for (int bin = 0; bin < prints[i].size(); ++bin) {
                dot += prints[i][bin] * prints[j][bin];
            }
            if (dot >= 0.999) {
                ++checks.repeatPairs;
            }
        }
    }
    return checks;
}

}  // namespace analysis
