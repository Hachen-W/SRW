#include "report.h"

#include <QCryptographicHash>
#include <QDateTime>
#include <QFile>
#include <QFileInfo>

#include "docx.h"
#include "plots.h"

namespace report {
namespace {

// Размер картинок в отчёте: точки растра и ширина на странице в пунктах
const QSize SpectrogramSize(1100, 320);
const QSize CurveSize(1100, 260);
constexpr double PageWidthPt = 460.0;

double heightFor(const QSize &size) {
    return PageWidthPt * size.height() / size.width();
}

QString number(double value, int digits) {
    return QString::number(value, 'f', digits);
}

}  // namespace

QString fileSha256(const QString &path) {
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) {
        return {};
    }
    QCryptographicHash hash(QCryptographicHash::Sha256);
    hash.addData(&file);
    return QString::fromLatin1(hash.result().toHex());
}

bool build(const QString &outPath, const Case &item, QString *error) {
    docx::Document doc;

    doc.addHeading(QStringLiteral("Заключение по исследованию фонограммы"), 0);
    doc.addParagraph(QStringLiteral("Дата формирования: %1")
                         .arg(QDateTime::currentDateTime()
                                  .toString("dd.MM.yyyy HH:mm")));

    // Объект исследования — исходный файл; для видео это сам видеофайл,
    // а анализировалась извлечённая из него дорожка.
    const QString source = item.source.isEmpty() ? item.path : item.source;

    doc.addHeading(QStringLiteral("1. Объект исследования"), 1);
    doc.addTable({QStringLiteral("Параметр"), QStringLiteral("Значение")},
                 {{QStringLiteral("Имя файла"), QFileInfo(source).fileName()},
                  {QStringLiteral("Размер, байт"),
                   QString::number(QFileInfo(source).size())},
                  {QStringLiteral("SHA-256"), fileSha256(source)},
                  {QStringLiteral("Контейнер / кодек"),
                   QStringLiteral("%1 / %2").arg(item.info.container,
                                                 item.info.codec)},
                  {QStringLiteral("Частота дискретизации, Гц"),
                   QString::number(item.signal.sampleRate)},
                  {QStringLiteral("Длительность, с"),
                   number(item.signal.duration(), 2)}});

    if (!item.source.isEmpty() && item.source != item.path) {
        doc.addParagraph(QStringLiteral(
            "Звуковая дорожка извлечена из видеофайла копированием потока, "
            "без перекодирования. Хеш и размер приведены для исходного файла."));
    }

    doc.addHeading(QStringLiteral("2. Применённые детекторы"), 1);
    if (item.results.isEmpty()) {
        doc.addParagraph(QStringLiteral("Детекторы не запускались."));
    } else {
        QVector<QStringList> rows;
        for (const auto &pair : item.results) {
            const Result &result = pair.second;
            double top = 0.0;
            for (double value : result.curve.probs) {
                top = std::max(top, value);
            }
            const QString verdict =
                result.service.value("verdict").toString(QStringLiteral("—"));
            rows.append({pair.first,
                         QString::number(result.curve.probs.size()),
                         result.curve.probs.isEmpty() ? QStringLiteral("—")
                                                      : number(top, 3),
                         QString::number(result.intervals.size()), verdict});
        }
        doc.addTable({QStringLiteral("Модель"), QStringLiteral("Оценок"),
                      QStringLiteral("Максимум"), QStringLiteral("Участков"),
                      QStringLiteral("Вердикт")},
                     rows);
        doc.addParagraph(QStringLiteral("Порог принятия решения: %1")
                             .arg(number(item.threshold, 2)));
    }

    doc.addHeading(QStringLiteral("3. Оценки во времени"), 1);
    const double duration = item.signal.duration();

    if (!item.signal.samples.isEmpty()) {
        doc.addParagraph(QStringLiteral("Спектрограмма фонограммы:"));
        const analysis::Spectrogram spec = analysis::spectrogramDb(item.signal);
        const QImage image =
            plots::renderSpectrogram(spec, SpectrogramSize, duration);
        doc.addImage(plots::imageToPng(image), PageWidthPt,
                     heightFor(SpectrogramSize));
    }

    // Сводный график — только когда моделей больше одной
    QVector<plots::Series> all;
    for (const auto &pair : item.results) {
        if (!pair.second.curve.times.isEmpty()) {
            all.append({pair.first, pair.second.curve, pair.second.intervals});
        }
    }
    if (all.size() > 1) {
        doc.addParagraph(QStringLiteral("Сводный график по всем моделям:"));
        const QImage image = plots::renderCurves(all, item.threshold, duration,
                                                 CurveSize);
        doc.addImage(plots::imageToPng(image), PageWidthPt,
                     heightFor(CurveSize));
    }

    // Отдельный график на каждую запущенную модель
    for (const auto &pair : item.results) {
        const Result &result = pair.second;
        if (result.curve.times.isEmpty()) {
            continue;
        }
        doc.addHeading(pair.first, 2);
        const QVector<plots::Series> series = {
            {pair.first, result.curve, result.intervals}};
        const QImage image = plots::renderCurves(series, item.threshold,
                                                 duration, CurveSize,
                                                 pair.first);
        doc.addImage(plots::imageToPng(image), PageWidthPt,
                     heightFor(CurveSize));

        if (result.intervals.isEmpty()) {
            doc.addParagraph(
                QStringLiteral("Участков выше порога не выявлено."));
        } else {
            doc.addParagraph(QStringLiteral("Участки выше порога:"));
            for (const analysis::Interval &interval : result.intervals) {
                doc.addBullet(QStringLiteral("%1 — %2 с")
                                  .arg(number(interval.start, 2),
                                       number(interval.end, 2)));
            }
        }
    }

    doc.addHeading(QStringLiteral("4. Классические признаки обработки"), 1);
    doc.addParagraph(QStringLiteral("Смещение постоянной составляющей: %1")
                         .arg(number(item.checks.dcOffset, 6)));
    doc.addParagraph(QStringLiteral("Частота среза спектра: %1 Гц")
                         .arg(number(item.checks.cutoffHz, 0)));
    doc.addParagraph(
        QStringLiteral("Участков с постоянным значением отсчётов: %1")
            .arg(item.checks.constantRuns.size()));
    doc.addParagraph(QStringLiteral("Пар повторяющихся фрагментов: %1")
                         .arg(item.checks.repeatPairs));
    if (item.info.lossy) {
        doc.addParagraph(QStringLiteral(
            "Фонограмма представлена в формате со сжатием с потерями. Частота "
            "среза спектра в этом случае объясняется работой кодека и не "
            "свидетельствует о редактировании. Исследование выполнено по "
            "декодированному сигналу."));
    }

    doc.addHeading(QStringLiteral("5. Журнал работы"), 1);
    if (item.journal.isEmpty()) {
        doc.addParagraph(QStringLiteral("Журнал пуст."));
    } else {
        QVector<QStringList> rows;
        for (const auto &entry : item.journal) {
            rows.append({entry.first, entry.second});
        }
        doc.addTable({QStringLiteral("Время"), QStringLiteral("Событие")}, rows);
    }

    doc.addHeading(QStringLiteral("6. Ограничения"), 1);
    doc.addParagraph(QStringLiteral(
        "Результат носит вероятностный характер и не является выводом о "
        "подлинности записи. Прототип не прошёл валидацию по методике "
        "экспертного учреждения; оценки на фонограммах, полученных неизвестными "
        "системами синтеза, могут быть занижены. Модели, возвращающие одну "
        "оценку на весь файл, показаны ровной линией — привязки к времени они "
        "не дают."));

    return doc.save(outPath, error);
}

}  // namespace report
