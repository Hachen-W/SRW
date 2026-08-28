#include "batch.h"

#include <QDirIterator>
#include <QFile>
#include <QFileInfo>
#include <QSet>
#include <QTextStream>

namespace batch {
namespace {

const QSet<QString> Extensions = {"wav", "mp3", "flac", "ogg", "opus", "m4a",
                                  "aac", "wma", "aiff", "amr", "mp4", "mkv",
                                  "avi", "mov"};

// В CSV разделитель — точка с запятой, значит его надо экранировать
QString escapeCsv(const QString &value) {
    if (value.contains(';') || value.contains('"') || value.contains('\n')) {
        QString quoted = value;
        quoted.replace('"', "\"\"");
        return '"' + quoted + '"';
    }
    return value;
}

}  // namespace

QStringList findFiles(const QString &folder) {
    QStringList found;
    QDirIterator iterator(folder, QDir::Files, QDirIterator::Subdirectories);
    while (iterator.hasNext()) {
        const QString path = iterator.next();
        if (Extensions.contains(QFileInfo(path).suffix().toLower())) {
            found.append(path);
        }
    }
    found.sort();
    return found;
}

Row processFile(const QString &path, detectors::Detector *detector,
                double threshold) {
    Row row;
    row.file = path;

    QString tempPath;
    QString error;
    QString workPath = path;

    if (analysis::isVideo(path)) {
        tempPath = analysis::extractAudio(path, 0, &error);
        if (tempPath.isEmpty()) {
            row.error = error;
            return row;
        }
        workPath = tempPath;
    }

    const analysis::Signal signal = analysis::loadAudio(workPath, &error);
    if (signal.samples.isEmpty()) {
        row.error = error.isEmpty() ? QStringLiteral("Файл не прочитан") : error;
    } else {
        row.duration = QString::number(signal.duration(), 'f', 2);

        // Ошибка на одном файле не прерывает пакет, а попадает в таблицу
        const analysis::Curve curve = detector->scores(signal, workPath, &error);
        row.scoreCount = QString::number(curve.probs.size());
        if (!curve.probs.isEmpty()) {
            double top = curve.probs.first();
            double sum = 0.0;
            for (double value : curve.probs) {
                top = std::max(top, value);
                sum += value;
            }
            row.maximum = QString::number(top, 'f', 4);
            row.average = QString::number(sum / curve.probs.size(), 'f', 4);
            row.intervals = QString::number(
                analysis::intervalsAbove(curve, threshold).size());
        }
        row.verdict = detector->lastResult().value("verdict").toString();
        row.error = error;
    }

    if (!tempPath.isEmpty()) {
        QFile::remove(tempPath);
    }
    return row;
}

QVector<Row> runFolder(const QString &folder, detectors::Detector *detector,
                       double threshold,
                       const std::function<void(const QString &)> &onProgress) {
    const QStringList files = findFiles(folder);
    QVector<Row> rows;
    for (int i = 0; i < files.size(); ++i) {
        if (onProgress) {
            onProgress(QStringLiteral("[%1/%2] %3")
                           .arg(i + 1)
                           .arg(files.size())
                           .arg(QFileInfo(files[i]).fileName()));
        }
        detector->clearLastResult();
        rows.append(processFile(files[i], detector, threshold));
    }
    return rows;
}

bool saveCsv(const QVector<Row> &rows, const QString &path, QString *error) {
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Text)) {
        if (error) {
            *error = QStringLiteral("Не удалось открыть файл для записи");
        }
        return false;
    }

    QTextStream stream(&file);
    stream.setEncoding(QStringConverter::Utf8);
    stream.setGenerateByteOrderMark(true);   // чтобы Excel не ломал кириллицу

    stream << "файл;длительность;оценок;максимум;средняя;участков;вердикт;"
              "ошибка\n";
    for (const Row &row : rows) {
        stream << escapeCsv(row.file) << ';' << row.duration << ';'
               << row.scoreCount << ';' << row.maximum << ';' << row.average
               << ';' << row.intervals << ';' << escapeCsv(row.verdict) << ';'
               << escapeCsv(row.error) << '\n';
    }
    file.close();
    return true;
}

}  // namespace batch
