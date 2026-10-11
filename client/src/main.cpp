#include <QApplication>
#include <QDebug>
#include <QEventLoop>
#include <QTimer>

#include "mainwindow.h"

int main(int argc, char *argv[]) {
    QApplication app(argc, argv);
    MainWindow window;
    window.show();

    // Самопроверка без диалогов: --selftest <файл>
    // Прогоняет весь путь и сохраняет снимок окна и отчёт в /tmp.
    const QStringList arguments = app.arguments();
    if (arguments.size() > 2 && arguments[1] == QLatin1String("--selftest")) {
        window.loadPath(arguments[2]);
        window.runAnalysis();

        QEventLoop loop;
        QTimer::singleShot(5000, &loop, &QEventLoop::quit);
        loop.exec();

        window.grab().save(QStringLiteral("/tmp/selftest_window.png"));
        QString error;
        if (!window.writeReport(QStringLiteral("/tmp/selftest_report.docx"),
                                &error)) {
            qWarning() << "отчёт не собран:" << error;
            return 1;
        }
        qInfo() << "самопроверка пройдена";
        return 0;
    }
    return app.exec();
}
