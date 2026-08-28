// Главное окно: загрузка фонограммы, выбор детектора, графики, отчёт.
#pragma once

#include <QFutureWatcher>
#include <QHash>
#include <QMainWindow>
#include <QVector>

#include <memory>

#include "analysis.h"
#include "batch.h"
#include "detectors.h"
#include "player.h"
#include "plots.h"
#include "report.h"

class QComboBox;
class QDoubleSpinBox;
class QHBoxLayout;
class QLabel;
class QPushButton;
class QTextEdit;
class QTimer;

// Результат работы детектора в фоновом потоке
struct AnalysisOutcome {
    analysis::Curve curve;
    QString error;
};

class MainWindow : public QMainWindow {
    Q_OBJECT

public:
    MainWindow();
    ~MainWindow() override;

    // Отделено от диалога, чтобы этим же путём шла самопроверка
    void loadPath(const QString &path);
    bool writeReport(const QString &path, QString *error);

protected:
    void closeEvent(QCloseEvent *event) override;

public slots:
    void openFile();
    void runAnalysis();

private slots:
    void onAnalysisDone();
    void runBatch();
    void onBatchDone();
    void saveReport();
    void togglePlay();
    void updateCursor();
    void rebuildParams();

private:
    double threshold() const;
    detectors::Detector *currentDetector() const;
    void log(const QString &text);
    void draw();
    void stopPlay();
    void moveCursor(double position);
    void cleanupTemp();

    // --- состояние сеанса ---
    QString m_path;          // что анализируем
    QString m_sourcePath;    // исходный файл, если звук извлечён из видео
    QString m_tempPath;      // извлечённая дорожка, удаляется при смене файла
    analysis::Signal m_signal;
    analysis::FormatInfo m_info;
    analysis::ClassicChecks m_checks;
    analysis::Spectrogram m_spec;
    bool m_hasChecks = false;
    QString m_modelName;
    analysis::Curve m_curve;
    QVector<QPair<QString, report::Result>> m_results;
    QVector<QPair<QString, QString>> m_journal;

    // --- виджеты ---
    QVector<std::shared_ptr<detectors::Detector>> m_detectors;
    QComboBox *m_detectorBox = nullptr;
    QDoubleSpinBox *m_thresholdBox = nullptr;
    QHBoxLayout *m_paramRow = nullptr;
    QHash<QString, QDoubleSpinBox *> m_paramWidgets;
    plots::PlotView *m_specView = nullptr;
    plots::PlotView *m_curveView = nullptr;
    QTextEdit *m_text = nullptr;
    QLabel *m_status = nullptr;
    QPushButton *m_playButton = nullptr;

    // --- фоновая работа ---
    QFutureWatcher<AnalysisOutcome> m_analysisWatcher;
    QFutureWatcher<QVector<batch::Row>> m_batchWatcher;
    Player m_player;
    QTimer *m_playTimer = nullptr;
};
