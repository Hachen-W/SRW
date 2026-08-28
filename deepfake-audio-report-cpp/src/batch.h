// Пакетная обработка папки: прогон детектора по всем фонограммам.
#pragma once

#include <QStringList>
#include <QVector>

#include <functional>

#include "detectors.h"

namespace batch {

// Одна строка сводной таблицы
struct Row {
    QString file;
    QString duration;
    QString scoreCount;
    QString maximum;
    QString average;
    QString intervals;
    QString verdict;
    QString error;
};

QStringList findFiles(const QString &folder);
Row processFile(const QString &path, detectors::Detector *detector,
                double threshold);
QVector<Row> runFolder(const QString &folder, detectors::Detector *detector,
                       double threshold,
                       const std::function<void(const QString &)> &onProgress);
bool saveCsv(const QVector<Row> &rows, const QString &path,
             QString *error = nullptr);

}  // namespace batch
