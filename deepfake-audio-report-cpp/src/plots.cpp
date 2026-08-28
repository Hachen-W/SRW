#include "plots.h"

#include <QBuffer>
#include <QFont>
#include <QPainter>
#include <QPen>

#include <cmath>

namespace plots {
namespace {

// Поля вокруг области графика
constexpr int Left = 58;
constexpr int Right = 14;
constexpr int Top = 20;
constexpr int Bottom = 28;

const QColor Background(255, 255, 255);
const QColor Axis(120, 120, 120);
const QColor Text(40, 40, 40);
const QColor Grid(225, 225, 225);
const QColor ThresholdColor(200, 40, 40);
const QColor IntervalColor(200, 40, 40, 60);
const QColor CursorColor(0, 150, 200);

// Цвета кривых, по одному на детектор
const QVector<QColor> SeriesColors = {
    QColor(31, 119, 180), QColor(255, 127, 14), QColor(44, 160, 44),
    QColor(148, 103, 189), QColor(140, 86, 75), QColor(23, 190, 207)};

// Опорные точки палитры спектрограммы: тёмный → светлый
struct ColorStop {
    double position;
    int red;
    int green;
    int blue;
};
const QVector<ColorStop> ColormapStops = {
    {0.00, 0, 0, 4},       {0.25, 80, 18, 123}, {0.50, 182, 54, 121},
    {0.75, 251, 136, 97},  {1.00, 252, 253, 191}};

QRgb colormap(double value) {
    value = std::clamp(value, 0.0, 1.0);
    for (int i = 1; i < ColormapStops.size(); ++i) {
        const ColorStop &left = ColormapStops[i - 1];
        const ColorStop &right = ColormapStops[i];
        if (value <= right.position) {
            const double span = right.position - left.position;
            const double share = span > 0 ? (value - left.position) / span : 0.0;
            const int red = int(left.red + (right.red - left.red) * share);
            const int green = int(left.green + (right.green - left.green) * share);
            const int blue = int(left.blue + (right.blue - left.blue) * share);
            return qRgb(red, green, blue);
        }
    }
    const ColorStop &last = ColormapStops.last();
    return qRgb(last.red, last.green, last.blue);
}

QImage new_canvas(const QSize &size) {
    QImage image(size, QImage::Format_RGB32);
    image.fill(Background);
    return image;
}

struct AxisLabel {
    double share;    // доля высоты снизу, 0..1
    QString text;
};

void drawAxes(QPainter &painter, const QRect &rect, double duration,
              const QVector<AxisLabel> &labels, const QString &xTitle,
              const QString &yTitle, bool grid) {
    painter.setFont(QFont("Sans", 7));

    for (const AxisLabel &label : labels) {
        const int y = int(rect.bottom() - rect.height() * label.share);
        if (grid) {
            // На спектрограмме сетку не рисуем: линии легли бы поверх данных
            painter.setPen(QPen(Grid, 1));
            painter.drawLine(rect.left(), y, rect.right(), y);
        }
        painter.setPen(Text);
        painter.drawText(QRect(0, y - 8, Left - 6, 16),
                         Qt::AlignRight | Qt::AlignVCenter, label.text);
    }

    // Подписи времени: около шести засечек на круглых значениях
    if (duration > 0) {
        const QVector<double> nice = {0.1, 0.2, 0.5, 1, 2, 5, 10,
                                      15, 30, 60, 120, 300, 600};
        const double rough = duration / 6.0;
        double step = nice.first();
        for (double candidate : nice) {
            if (std::abs(candidate - rough) < std::abs(step - rough)) {
                step = candidate;
            }
        }
        for (double tick = 0.0; tick <= duration; tick += step) {
            const int x = timeToX(tick, duration, rect);
            painter.setPen(QPen(Axis, 1));
            painter.drawLine(x, rect.bottom(), x, rect.bottom() + 4);
            painter.setPen(Text);
            painter.drawText(QRect(x - 30, rect.bottom() + 5, 60, 14),
                             Qt::AlignHCenter | Qt::AlignTop,
                             QString::number(tick, 'g', 4));
        }
    }

    painter.setPen(QPen(Axis, 1));
    painter.drawRect(rect);

    painter.setPen(Text);
    painter.drawText(QRect(rect.left(), rect.bottom() + 13, rect.width(), 14),
                     Qt::AlignRight | Qt::AlignTop, xTitle);
    if (!yTitle.isEmpty()) {
        painter.save();
        painter.translate(12, rect.center().y());
        painter.rotate(-90);
        painter.drawText(QRect(-rect.height() / 2, -8, rect.height(), 16),
                         Qt::AlignHCenter | Qt::AlignVCenter, yTitle);
        painter.restore();
    }
}

}  // namespace

QRect plotRect(const QSize &size) {
    return QRect(Left, Top, std::max(size.width() - Left - Right, 1),
                 std::max(size.height() - Top - Bottom, 1));
}

int timeToX(double value, double duration, const QRect &rect) {
    if (duration <= 0) {
        return rect.left();
    }
    return int(rect.left() + rect.width() * value / duration);
}

QImage renderSpectrogram(const analysis::Spectrogram &spec, const QSize &size,
                         double duration) {
    QImage image = new_canvas(size);
    if (spec.power.isEmpty() || spec.power.first().isEmpty()) {
        return image;
    }

    const int bins = spec.power.size();
    const int frames = spec.power.first().size();

    double top = spec.power[0][0];
    for (int bin = 0; bin < bins; ++bin) {
        for (int frame = 0; frame < frames; ++frame) {
            top = std::max(top, spec.power[bin][frame]);
        }
    }
    const double bottom = top - 100.0;
    const double span = std::max(top - bottom, 1e-9);

    // Строка 0 картинки — верх, поэтому переворачиваем по частоте
    QImage specImage(frames, bins, QImage::Format_RGB32);
    for (int bin = 0; bin < bins; ++bin) {
        QRgb *line = reinterpret_cast<QRgb *>(specImage.scanLine(bins - 1 - bin));
        for (int frame = 0; frame < frames; ++frame) {
            line[frame] = colormap((spec.power[bin][frame] - bottom) / span);
        }
    }

    const QRect rect = plotRect(size);
    QPainter painter(&image);
    painter.drawImage(rect, specImage);

    // duration задаёт шкалу времени — ту же, что у графика оценок, иначе
    // отметка воспроизведения на двух графиках разъезжается
    if (duration < 0) {
        duration = spec.times.isEmpty() ? 0.0 : spec.times.last();
    }
    const double topFreq = spec.freqs.isEmpty() ? 0.0 : spec.freqs.last();
    QVector<AxisLabel> labels;
    for (double share : {0.0, 0.25, 0.5, 0.75, 1.0}) {
        labels.append({share, QString::number(topFreq * share / 1000.0, 'f', 1)
                                  + QStringLiteral("к")});
    }
    drawAxes(painter, rect, duration, labels, QStringLiteral("Время, с"),
             QStringLiteral("Частота, Гц"), false);
    painter.end();
    return image;
}

QImage renderCurves(const QVector<Series> &series, double threshold,
                    double duration, const QSize &size, const QString &title) {
    QImage image = new_canvas(size);
    const QRect rect = plotRect(size);
    QPainter painter(&image);
    painter.setRenderHint(QPainter::Antialiasing);

    // Подсветка участков выше порога — только когда кривая одна
    if (series.size() == 1) {
        for (const analysis::Interval &interval : series.first().intervals) {
            const int x0 = timeToX(interval.start, duration, rect);
            const int x1 = timeToX(interval.end, duration, rect);
            painter.fillRect(QRect(x0, rect.top(), std::max(x1 - x0, 1),
                                   rect.height()),
                             IntervalColor);
        }
    }

    QVector<AxisLabel> labels;
    for (double share : {0.0, 0.25, 0.5, 0.75, 1.0}) {
        labels.append({share, QString::number(share, 'f', 2)});
    }
    drawAxes(painter, rect, duration, labels, QStringLiteral("Время, с"),
             QStringLiteral("Оценка"), true);

    const int thresholdY = int(rect.bottom() - rect.height() * threshold);
    painter.setPen(QPen(ThresholdColor, 1, Qt::DashLine));
    painter.drawLine(rect.left(), thresholdY, rect.right(), thresholdY);

    painter.setFont(QFont("Sans", 7));
    int legendY = rect.top() + 4;
    for (int number = 0; number < series.size(); ++number) {
        const analysis::Curve &curve = series[number].curve;
        const QColor color = SeriesColors[number % SeriesColors.size()];
        painter.setPen(QPen(color, 2));

        QPoint previous;
        bool hasPrevious = false;
        for (int i = 0; i < curve.times.size(); ++i) {
            const double value = std::clamp(curve.probs[i], 0.0, 1.0);
            const QPoint point(timeToX(curve.times[i], duration, rect),
                               int(rect.bottom() - rect.height() * value));
            if (hasPrevious) {
                painter.drawLine(previous, point);
            }
            previous = point;
            hasPrevious = true;
        }

        if (series.size() > 1) {
            painter.drawLine(rect.right() - 120, legendY + 5,
                             rect.right() - 105, legendY + 5);
            painter.setPen(Text);
            painter.drawText(QRect(rect.right() - 100, legendY - 2, 96, 14),
                             Qt::AlignLeft | Qt::AlignVCenter,
                             series[number].name);
            legendY += 13;
        }
    }

    if (!title.isEmpty()) {
        painter.setPen(Text);
        painter.setFont(QFont("Sans", 8));
        painter.drawText(QRect(rect.left(), 2, rect.width(), Top - 4),
                         Qt::AlignLeft | Qt::AlignVCenter, title);
    }
    painter.end();
    return image;
}

QByteArray imageToPng(const QImage &image) {
    QByteArray data;
    QBuffer buffer(&data);
    buffer.open(QIODevice::WriteOnly);
    image.save(&buffer, "PNG");
    buffer.close();
    return data;
}

PlotView::PlotView(int minimumHeight, QWidget *parent) : QWidget(parent) {
    setMinimumHeight(minimumHeight);
}

void PlotView::setContent(Renderer renderer, double duration) {
    m_renderer = std::move(renderer);
    m_duration = duration;
    m_image = QImage();
    update();
}

void PlotView::clearContent() {
    m_renderer = nullptr;
    m_image = QImage();
    m_cursor = -1.0;
    update();
}

void PlotView::setCursorPosition(double position) {
    m_cursor = position;
    update();
}

void PlotView::resizeEvent(QResizeEvent *event) {
    m_image = QImage();   // при новом размере рисуем заново
    QWidget::resizeEvent(event);
}

void PlotView::paintEvent(QPaintEvent *) {
    QPainter painter(this);
    painter.fillRect(rect(), Background);
    if (!m_renderer) {
        return;
    }
    if (m_image.isNull()) {
        m_image = m_renderer(size());
    }
    painter.drawImage(0, 0, m_image);

    if (m_cursor >= 0.0 && m_duration > 0.0) {
        const QRect area = plotRect(size());
        const int x = timeToX(m_cursor, m_duration, area);
        painter.setPen(QPen(CursorColor, 1));
        painter.drawLine(x, area.top(), x, area.bottom());
    }
}

}  // namespace plots
