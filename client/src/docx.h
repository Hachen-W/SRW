// Минимальный генератор DOCX.
//
// Готовой замены python-docx в C++ нет, поэтому пакет OOXML собирается
// вручную: несколько XML-файлов складываются в zip без сжатия.
#pragma once

#include <QByteArray>
#include <QString>
#include <QStringList>
#include <QVector>

namespace docx {

class Document {
public:
    void addHeading(const QString &text, int level);
    void addParagraph(const QString &text);
    void addBullet(const QString &text);
    void addTable(const QStringList &headers,
                  const QVector<QStringList> &rows);
    // widthPt — ширина картинки в пунктах (72 pt = 1 дюйм)
    void addImage(const QByteArray &png, double widthPt, double heightPt);

    bool save(const QString &path, QString *error = nullptr) const;

private:
    QString m_body;
    QVector<QByteArray> m_images;
};

}  // namespace docx
