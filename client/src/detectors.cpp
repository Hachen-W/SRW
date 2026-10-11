#include "detectors.h"

#include "config.h"
#include "service.h"

namespace detectors {

double Detector::value(const QString &key) const {
    if (m_values.contains(key)) {
        return m_values.value(key);
    }
    for (const Field &field : m_fields) {
        if (field.key == key) {
            return field.defaultValue;
        }
    }
    return 0.0;
}

BaselineDetector::BaselineDetector() {
    m_name = QStringLiteral("ЗАГЛУШКА (локально)");
    m_fields = {{"window", QStringLiteral("Окно, с"), config::Window},
                {"hop", QStringLiteral("Шаг, с"), config::Hop}};
}

analysis::Curve BaselineDetector::scores(const analysis::Signal &signal,
                                         const QString &, QString *) {
    return analysis::frameProbabilities(signal, value("window"), value("hop"));
}

SrwStreamDetector::SrwStreamDetector(const QString &model, const QString &title)
    : m_model(model) {
    m_name = title;
    m_fields = {{"chunk", QStringLiteral("Чанк, с"), config::ChunkSeconds},
                {"idle", QStringLiteral("Тишина, с"), config::StreamIdle},
                {"timeout", QStringLiteral("Таймаут, с"), config::StreamTimeout}};
}

analysis::Curve SrwStreamDetector::scores(const analysis::Signal &signal,
                                          const QString &, QString *error) {
    service::Client client;
    return client.streamScores(signal, m_model, value("chunk"), value("idle"),
                               value("timeout"), error);
}

SrwQueueDetector::SrwQueueDetector(const QString &model, const QString &title)
    : m_model(model) {
    m_name = title;
    m_fields = {{"poll", QStringLiteral("Опрос, с"), config::PollInterval},
                {"timeout", QStringLiteral("Таймаут, с"), config::ResultTimeout},
                {"retry", QStringLiteral("Пауза 429, с"), config::RetryPause}};
}

analysis::Curve SrwQueueDetector::scores(const analysis::Signal &signal,
                                         const QString &path, QString *error) {
    service::Client client;
    m_lastResult = client.analyze(path, m_model, value("poll"),
                                  value("timeout"), value("retry"), error);

    analysis::Curve curve;
    if (m_lastResult.value("status").toString() != "completed") {
        return curve;
    }
    const double prediction = m_lastResult.value("prediction").toDouble();
    curve.times = {0.0, signal.duration()};
    curve.probs = {prediction, prediction};
    return curve;
}

QVector<std::shared_ptr<Detector>> available() {
    QVector<std::shared_ptr<Detector>> result;
    result.append(std::make_shared<BaselineDetector>());
    result.append(std::make_shared<SrwStreamDetector>(
        "pytorch", QStringLiteral("SRW: PyTorch — поток")));
    result.append(std::make_shared<SrwStreamDetector>(
        "pyara", QStringLiteral("SRW: PyAra — поток")));
    result.append(std::make_shared<SrwQueueDetector>(
        "pytorch", QStringLiteral("SRW: PyTorch — файл целиком")));
    result.append(std::make_shared<SrwQueueDetector>(
        "pyara", QStringLiteral("SRW: PyAra — файл целиком")));
    return result;
}

}  // namespace detectors
