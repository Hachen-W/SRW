// Формирование отчёта в DOCX по всему сеансу работы.
#pragma once

#include <QJsonObject>
#include <QPair>
#include <QString>
#include <QVector>

#include "analysis.h"

namespace report {

// Результат одного детектора
struct Result {
    analysis::Curve curve;
    QVector<analysis::Interval> intervals;
    QJsonObject service;    // вердикт целиком, если модель его даёт
};

// Всё, что известно о сеансе. Порядок результатов — порядок запуска.
struct Case {
    QString path;       // что анализировали
    QString source;     // исходный файл (для видео отличается от path)
    analysis::Signal signal;
    analysis::FormatInfo info;
    analysis::ClassicChecks checks;
    double threshold = 0.7;
    QVector<QPair<QString, Result>> results;
    QVector<QPair<QString, QString>> journal;   // время, событие
};

QString fileSha256(const QString &path);
bool build(const QString &outPath, const Case &item, QString *error);

}  // namespace report
