// Детекторы синтезированной речи с общим интерфейсом.
//
// Каждый детектор получает сигнал и возвращает кривую оценок во времени,
// поэтому интерфейс приложения одинаково работает с любым из них.
// Модели, которые дают одну оценку на весь файл, возвращают ровную линию.
//
// Поле fields описывает настройки детектора: интерфейс строит по нему поля
// ввода, а перед запуском кладёт введённые значения в values.
#pragma once

#include <QHash>
#include <QJsonObject>
#include <QString>
#include <QVector>

#include <memory>

#include "analysis.h"

namespace detectors {

struct Field {
    QString key;
    QString label;
    double defaultValue;
};

class Detector {
public:
    virtual ~Detector() = default;

    QString name() const { return m_name; }
    const QVector<Field> &fields() const { return m_fields; }

    void setValues(const QHash<QString, double> &values) { m_values = values; }
    double value(const QString &key) const;

    // Вердикт целиком, если модель его даёт
    QJsonObject lastResult() const { return m_lastResult; }
    void clearLastResult() { m_lastResult = {}; }

    virtual analysis::Curve scores(const analysis::Signal &signal,
                                   const QString &path, QString *error) = 0;

protected:
    QString m_name;
    QVector<Field> m_fields;
    QHash<QString, double> m_values;
    QJsonObject m_lastResult;
};

// ЗАГЛУШКА, а не детектор. Две спектральные характеристики, чтобы интерфейс
// работал без моделей. Результаты нельзя выдавать за детектирование.
class BaselineDetector : public Detector {
public:
    BaselineDetector();
    analysis::Curve scores(const analysis::Signal &signal, const QString &path,
                           QString *error) override;
};

// Модель сервиса в потоковом режиме: даёт кривую по всему файлу.
class SrwStreamDetector : public Detector {
public:
    SrwStreamDetector(const QString &model, const QString &title);
    analysis::Curve scores(const analysis::Signal &signal, const QString &path,
                           QString *error) override;

private:
    QString m_model;
};

// Модель сервиса через очередь: одна оценка на весь файл. Рисуется ровной
// линией, потому что привязки ко времени сервис не даёт.
class SrwQueueDetector : public Detector {
public:
    SrwQueueDetector(const QString &model, const QString &title);
    analysis::Curve scores(const analysis::Signal &signal, const QString &path,
                           QString *error) override;

private:
    QString m_model;
};

// Детекторы, которые можно выбрать в интерфейсе.
QVector<std::shared_ptr<Detector>> available();

}  // namespace detectors
