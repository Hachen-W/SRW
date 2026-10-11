// Отрисовка графиков. Один и тот же код рисует и в окно, и в картинки отчёта.
#pragma once

#include <QImage>
#include <functional>
#include <QRect>
#include <QSize>
#include <QString>
#include <QVector>
#include <QWidget>

#include "analysis.h"

namespace plots {

// Одна кривая на графике оценок
struct Series {
    QString name;
    analysis::Curve curve;
    QVector<analysis::Interval> intervals;
};

QRect plotRect(const QSize &size);
int timeToX(double value, double duration, const QRect &rect);

QImage renderSpectrogram(const analysis::Spectrogram &spec, const QSize &size,
                         double duration = -1.0);
QImage renderCurves(const QVector<Series> &series, double threshold,
                    double duration, const QSize &size,
                    const QString &title = QString());
QByteArray imageToPng(const QImage &image);

// Показывает картинку графика и отметку позиции воспроизведения.
class PlotView : public QWidget {
    Q_OBJECT

public:
    // Функция получает размер виджета и возвращает готовую картинку
    using Renderer = std::function<QImage(const QSize &)>;

    explicit PlotView(int minimumHeight = 160, QWidget *parent = nullptr);

    void setContent(Renderer renderer, double duration);
    void clearContent();
    void setCursorPosition(double position);   // отрицательное — спрятать

protected:
    void paintEvent(QPaintEvent *event) override;
    void resizeEvent(QResizeEvent *event) override;

private:
    Renderer m_renderer;
    QImage m_image;
    double m_duration = 0.0;
    double m_cursor = -1.0;
};

}  // namespace plots
