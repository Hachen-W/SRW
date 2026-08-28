#include "mainwindow.h"

#include <QCloseEvent>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFileDialog>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QInputDialog>
#include <QLabel>
#include <QPushButton>
#include <QTextEdit>
#include <QTime>
#include <QTimer>
#include <QVBoxLayout>
#include <QtConcurrent>

#include "config.h"

namespace {

const QString FileFilter = QStringLiteral(
    "Аудио и видео (*.wav *.mp3 *.flac *.ogg *.opus *.m4a *.aac *.wma "
    "*.aiff *.amr *.mp4 *.mkv *.avi *.mov);;Все файлы (*)");

}  // namespace

MainWindow::MainWindow() {
    setWindowTitle(QStringLiteral("Анализ фонограммы — прототип"));
    resize(1000, 700);

    m_detectors = detectors::available();
    m_detectorBox = new QComboBox();
    for (const auto &detector : m_detectors) {
        m_detectorBox->addItem(detector->name());
    }
    connect(m_detectorBox, &QComboBox::currentIndexChanged, this,
            &MainWindow::rebuildParams);

    // Порог общий для всех детекторов: по нему выделяются участки
    m_thresholdBox = new QDoubleSpinBox();
    m_thresholdBox->setRange(0.0, 1.0);
    m_thresholdBox->setSingleStep(0.05);
    m_thresholdBox->setDecimals(2);
    m_thresholdBox->setValue(config::Threshold);
    connect(m_thresholdBox, &QDoubleSpinBox::valueChanged, this,
            [this](double) { draw(); });

    m_specView = new plots::PlotView(200);
    m_curveView = new plots::PlotView(160);
    m_text = new QTextEdit();
    m_text->setReadOnly(true);
    m_text->setMaximumHeight(160);
    m_status = new QLabel(QStringLiteral("Файл не выбран"));

    auto *openButton = new QPushButton(QStringLiteral("Открыть файл"));
    connect(openButton, &QPushButton::clicked, this, &MainWindow::openFile);
    m_playButton = new QPushButton(QStringLiteral("Слушать"));
    connect(m_playButton, &QPushButton::clicked, this, &MainWindow::togglePlay);
    auto *runButton = new QPushButton(QStringLiteral("Анализ"));
    connect(runButton, &QPushButton::clicked, this, &MainWindow::runAnalysis);
    auto *batchButton = new QPushButton(QStringLiteral("Папка"));
    connect(batchButton, &QPushButton::clicked, this, &MainWindow::runBatch);
    auto *reportButton = new QPushButton(QStringLiteral("Отчёт DOCX"));
    connect(reportButton, &QPushButton::clicked, this, &MainWindow::saveReport);

    // Первая строка — кнопки
    auto *buttons = new QHBoxLayout();
    buttons->addWidget(openButton);
    buttons->addWidget(m_playButton);
    buttons->addWidget(m_detectorBox);
    buttons->addWidget(runButton);
    buttons->addWidget(batchButton);
    buttons->addWidget(reportButton);
    buttons->addWidget(m_status);
    buttons->addStretch();

    // Вторая строка — всё, что калибруется
    m_paramRow = new QHBoxLayout();
    auto *numbers = new QHBoxLayout();
    numbers->addWidget(new QLabel(QStringLiteral("Порог")));
    numbers->addWidget(m_thresholdBox);
    numbers->addLayout(m_paramRow);

    auto *layout = new QVBoxLayout();
    layout->addLayout(buttons);
    layout->addLayout(numbers);
    layout->addWidget(m_specView, 3);
    layout->addWidget(m_curveView, 2);
    layout->addWidget(m_text);

    auto *central = new QWidget();
    central->setLayout(layout);
    setCentralWidget(central);

    m_playTimer = new QTimer(this);
    m_playTimer->setInterval(100);
    connect(m_playTimer, &QTimer::timeout, this, &MainWindow::updateCursor);

    connect(&m_analysisWatcher, &QFutureWatcher<AnalysisOutcome>::finished,
            this, &MainWindow::onAnalysisDone);
    connect(&m_batchWatcher, &QFutureWatcher<QVector<batch::Row>>::finished,
            this, &MainWindow::onBatchDone);

    rebuildParams();
}

MainWindow::~MainWindow() {
    cleanupTemp();
}

void MainWindow::closeEvent(QCloseEvent *event) {
    stopPlay();
    cleanupTemp();
    QMainWindow::closeEvent(event);
}

double MainWindow::threshold() const {
    return m_thresholdBox->value();
}

detectors::Detector *MainWindow::currentDetector() const {
    return m_detectors[m_detectorBox->currentIndex()].get();
}

void MainWindow::log(const QString &text) {
    const QString stamp = QTime::currentTime().toString("HH:mm:ss");
    m_journal.append({stamp, text});
    m_text->append(QStringLiteral("[%1] %2").arg(stamp, text));
}

void MainWindow::rebuildParams() {
    // Пересобираем поля настроек под выбранный детектор
    while (QLayoutItem *item = m_paramRow->takeAt(0)) {
        if (item->widget()) {
            item->widget()->deleteLater();
        }
        delete item;
    }
    m_paramWidgets.clear();

    detectors::Detector *detector = currentDetector();
    for (const detectors::Field &field : detector->fields()) {
        auto *spin = new QDoubleSpinBox();
        spin->setRange(0.05, 3600.0);
        spin->setDecimals(2);
        spin->setSingleStep(0.5);
        spin->setValue(detector->value(field.key));
        m_paramRow->addWidget(new QLabel(field.label));
        m_paramRow->addWidget(spin);
        m_paramWidgets.insert(field.key, spin);
    }
    m_paramRow->addStretch();
}

void MainWindow::cleanupTemp() {
    // Удаляем дорожку, извлечённую из предыдущего видео
    if (!m_tempPath.isEmpty()) {
        QFile::remove(m_tempPath);
        m_tempPath.clear();
    }
}

void MainWindow::openFile() {
    const QString path =
        QFileDialog::getOpenFileName(this, QStringLiteral("Выберите файл"),
                                     QString(), FileFilter);
    if (!path.isEmpty()) {
        loadPath(path);
    }
}

void MainWindow::loadPath(const QString &path) {
    stopPlay();
    cleanupTemp();
    m_sourcePath = path;
    QString workPath = path;
    int index = 0;

    if (analysis::isVideo(path)) {
        const QVector<analysis::AudioStream> streams =
            analysis::listAudioStreams(path);
        if (streams.isEmpty()) {
            log(QStringLiteral("В видеофайле нет звуковых дорожек"));
            return;
        }
        if (streams.size() > 1) {
            QStringList labels;
            for (const analysis::AudioStream &stream : streams) {
                labels.append(QStringLiteral("%1: %2, %3 кан., %4 Гц %5")
                                  .arg(stream.index)
                                  .arg(stream.codec)
                                  .arg(stream.channels)
                                  .arg(stream.sampleRate)
                                  .arg(stream.language)
                                  .trimmed());
            }
            bool ok = false;
            const QString choice = QInputDialog::getItem(
                this, QStringLiteral("Звуковые дорожки"),
                QStringLiteral("Какую дорожку исследуем?"), labels, 0, false,
                &ok);
            if (!ok) {
                return;
            }
            index = labels.indexOf(choice);
        }
        QString error;
        m_tempPath = analysis::extractAudio(path, index, &error);
        if (m_tempPath.isEmpty()) {
            log(error);
            return;
        }
        workPath = m_tempPath;
    }

    QString error;
    const analysis::Signal signal = analysis::loadAudio(workPath, &error);
    if (signal.samples.isEmpty()) {
        m_text->clear();
        log(error);
        return;
    }

    m_path = workPath;
    m_signal = signal;
    m_info = analysis::probeFormat(workPath);
    m_curve = {};
    m_modelName.clear();
    m_spec = {};                 // новая запись — новая спектрограмма
    m_results.clear();
    m_journal.clear();
    m_text->clear();

    m_status->setText(QFileInfo(path).fileName());
    if (!m_tempPath.isEmpty()) {
        log(QStringLiteral("Из видео %1 извлечена дорожка %2 без перекодирования")
                .arg(QFileInfo(path).fileName())
                .arg(index));
    }
    const QString note = m_info.lossy
                             ? QStringLiteral(" — сжатие с потерями")
                             : QString();
    log(QStringLiteral("Загружен %1: %2%3, %4 Гц, %5 с")
            .arg(QFileInfo(path).fileName(), m_info.codec, note)
            .arg(m_signal.sampleRate)
            .arg(m_signal.duration(), 0, 'f', 2));

    m_checks = analysis::classicChecks(m_signal);
    m_hasChecks = true;
    log(QStringLiteral("Классические проверки: смещение %1, срез %2 Гц, "
                       "постоянных участков %3, повторов %4")
            .arg(m_checks.dcOffset, 0, 'f', 6)
            .arg(m_checks.cutoffHz, 0, 'f', 0)
            .arg(m_checks.constantRuns.size())
            .arg(m_checks.repeatPairs));

    draw();
}

void MainWindow::runAnalysis() {
    if (m_signal.samples.isEmpty() || m_analysisWatcher.isRunning()) {
        return;
    }

    detectors::Detector *detector = currentDetector();
    QHash<QString, double> values;
    for (auto it = m_paramWidgets.constBegin(); it != m_paramWidgets.constEnd();
         ++it) {
        values.insert(it.key(), it.value()->value());
    }
    detector->setValues(values);
    detector->clearLastResult();

    QStringList settings;
    for (const detectors::Field &field : detector->fields()) {
        settings.append(QStringLiteral("%1 %2").arg(
            field.label, QString::number(detector->value(field.key))));
    }
    log(QStringLiteral("Запуск детектора: %1 (%2, порог %3)")
            .arg(detector->name(), settings.join(", "),
                 QString::number(threshold())));

    const analysis::Signal signal = m_signal;
    const QString path = m_path;
    m_analysisWatcher.setFuture(
        QtConcurrent::run([detector, signal, path]() -> AnalysisOutcome {
            AnalysisOutcome outcome;
            outcome.curve = detector->scores(signal, path, &outcome.error);
            return outcome;
        }));
}

void MainWindow::onAnalysisDone() {
    const AnalysisOutcome outcome = m_analysisWatcher.result();
    detectors::Detector *detector = currentDetector();
    const QJsonObject service = detector->lastResult();

    if (outcome.curve.probs.isEmpty()) {
        if (!outcome.error.isEmpty()) {
            log(QStringLiteral("%1: ошибка — %2")
                    .arg(detector->name(), outcome.error));
        } else if (!service.isEmpty()) {
            log(QStringLiteral("%1: %2 — %3")
                    .arg(detector->name(),
                         service.value("status").toString(),
                         service.value("reason").toString()));
        } else {
            log(QStringLiteral("%1: оценок не получено").arg(detector->name()));
        }
        return;
    }

    const QVector<analysis::Interval> intervals =
        analysis::intervalsAbove(outcome.curve, threshold());
    m_curve = outcome.curve;
    m_modelName = detector->name();

    report::Result result;
    result.curve = outcome.curve;
    result.intervals = intervals;
    result.service = service;

    bool replaced = false;
    for (auto &pair : m_results) {
        if (pair.first == detector->name()) {
            pair.second = result;
            replaced = true;
            break;
        }
    }
    if (!replaced) {
        m_results.append({detector->name(), result});
    }

    double top = outcome.curve.probs.first();
    for (double value : outcome.curve.probs) {
        top = std::max(top, value);
    }
    log(QStringLiteral("%1: оценок %2, максимум %3, участков выше порога %4")
            .arg(detector->name())
            .arg(outcome.curve.probs.size())
            .arg(top, 0, 'f', 3)
            .arg(intervals.size()));
    if (!service.isEmpty()) {
        log(QStringLiteral("%1: вердикт сервиса %2")
                .arg(detector->name(), service.value("verdict").toString()));
    }
    for (const analysis::Interval &interval : intervals) {
        log(QStringLiteral("%1: участок %2 — %3 с")
                .arg(detector->name())
                .arg(interval.start, 0, 'f', 2)
                .arg(interval.end, 0, 'f', 2));
    }
    draw();
}

void MainWindow::draw() {
    if (m_signal.samples.isEmpty()) {
        return;
    }
    const double duration = m_signal.duration();

    if (m_spec.power.isEmpty()) {
        m_spec = analysis::spectrogramDb(m_signal);
    }
    const analysis::Spectrogram spec = m_spec;
    m_specView->setContent(
        [spec, duration](const QSize &size) {
            return plots::renderSpectrogram(spec, size, duration);
        },
        duration);

    if (m_curve.probs.isEmpty()) {
        m_curveView->clearContent();
        return;
    }

    plots::Series series;
    series.name = m_modelName;
    series.curve = m_curve;
    series.intervals = analysis::intervalsAbove(m_curve, threshold());

    const QVector<plots::Series> all = {series};
    const double level = threshold();
    const QString title = m_modelName;
    m_curveView->setContent(
        [all, level, duration, title](const QSize &size) {
            return plots::renderCurves(all, level, duration, size, title);
        },
        duration);
}

void MainWindow::runBatch() {
    if (m_batchWatcher.isRunning()) {
        return;
    }
    const QString folder =
        QFileDialog::getExistingDirectory(this, QStringLiteral("Выберите папку"));
    if (folder.isEmpty()) {
        return;
    }

    detectors::Detector *detector = currentDetector();
    QHash<QString, double> values;
    for (auto it = m_paramWidgets.constBegin(); it != m_paramWidgets.constEnd();
         ++it) {
        values.insert(it.key(), it.value()->value());
    }
    detector->setValues(values);

    const int count = batch::findFiles(folder).size();
    if (count == 0) {
        log(QStringLiteral("В папке нет подходящих файлов"));
        return;
    }
    log(QStringLiteral("Пакетная обработка: %1 файлов, детектор %2")
            .arg(count)
            .arg(detector->name()));

    const double level = threshold();
    m_batchWatcher.setFuture(QtConcurrent::run([folder, detector, level]() {
        return batch::runFolder(folder, detector, level, nullptr);
    }));
}

void MainWindow::onBatchDone() {
    const QVector<batch::Row> rows = m_batchWatcher.result();
    int errors = 0;
    for (const batch::Row &row : rows) {
        if (!row.error.isEmpty()) {
            ++errors;
        }
    }
    log(QStringLiteral("Пакет завершён: %1 файлов, ошибок %2")
            .arg(rows.size())
            .arg(errors));

    const QString path = QFileDialog::getSaveFileName(
        this, QStringLiteral("Сохранить таблицу"), QStringLiteral("batch.csv"),
        QStringLiteral("CSV (*.csv)"));
    if (path.isEmpty()) {
        return;
    }
    QString error;
    if (batch::saveCsv(rows, path, &error)) {
        log(QStringLiteral("Таблица сохранена: %1").arg(path));
    } else {
        log(error);
    }
}

void MainWindow::saveReport() {
    if (!m_hasChecks) {
        return;
    }
    const QString path = QFileDialog::getSaveFileName(
        this, QStringLiteral("Сохранить отчёт"), QStringLiteral("report.docx"),
        QStringLiteral("DOCX (*.docx)"));
    if (path.isEmpty()) {
        return;
    }

    QString error;
    if (writeReport(path, &error)) {
        log(QStringLiteral("Отчёт сохранён: %1").arg(path));
    } else {
        log(error);
    }
}

bool MainWindow::writeReport(const QString &path, QString *error) {
    report::Case item;
    item.path = m_path;
    item.source = m_sourcePath;
    item.signal = m_signal;
    item.info = m_info;
    item.checks = m_checks;
    item.threshold = threshold();
    item.results = m_results;
    item.journal = m_journal;

    return report::build(path, item, error);
}

void MainWindow::togglePlay() {
    if (m_signal.samples.isEmpty()) {
        return;
    }
    if (m_playTimer->isActive()) {
        stopPlay();
        return;
    }
    QString error;
    if (!m_player.play(m_signal, &error)) {
        log(QStringLiteral("Не удалось воспроизвести: %1").arg(error));
        return;
    }
    m_playButton->setText(QStringLiteral("Стоп"));
    m_playTimer->start();
}

void MainWindow::stopPlay() {
    m_playTimer->stop();
    m_player.stop();
    m_playButton->setText(QStringLiteral("Слушать"));
    moveCursor(-1.0);
}

void MainWindow::updateCursor() {
    if (!m_player.isPlaying()) {
        stopPlay();
        return;
    }
    moveCursor(m_player.position());
}

void MainWindow::moveCursor(double position) {
    m_specView->setCursorPosition(position);
    m_curveView->setCursorPosition(position);
}
