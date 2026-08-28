#include "docx.h"

#include <QDataStream>
#include <QFile>

#include <zlib.h>

namespace docx {
namespace {

// В XML нельзя оставлять служебные символы как есть
QString escape(const QString &text) {
    QString result = text;
    result.replace('&', "&amp;");
    result.replace('<', "&lt;");
    result.replace('>', "&gt;");
    return result;
}

// Один файл внутри архива
struct ZipEntry {
    QString name;
    QByteArray data;
    quint32 crc = 0;
    quint32 offset = 0;
};

void writeUInt16(QDataStream &stream, quint16 value) { stream << value; }
void writeUInt32(QDataStream &stream, quint32 value) { stream << value; }

// Пишем архив методом «без сжатия»: так не нужен deflate, а Word такие
// файлы принимает наравне со сжатыми.
bool writeZip(const QString &path, QVector<ZipEntry> entries, QString *error) {
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly)) {
        if (error) {
            *error = QStringLiteral("Не удалось открыть файл для записи");
        }
        return false;
    }
    QDataStream stream(&file);
    stream.setByteOrder(QDataStream::LittleEndian);

    for (ZipEntry &entry : entries) {
        entry.crc = crc32(0, reinterpret_cast<const Bytef *>(entry.data.constData()),
                          entry.data.size());
        entry.offset = quint32(file.pos());
        const QByteArray name = entry.name.toUtf8();

        writeUInt32(stream, 0x04034b50);          // сигнатура локальной записи
        writeUInt16(stream, 20);                  // версия
        writeUInt16(stream, 0);                   // флаги
        writeUInt16(stream, 0);                   // метод: без сжатия
        writeUInt16(stream, 0);                   // время
        writeUInt16(stream, 0);                   // дата
        writeUInt32(stream, entry.crc);
        writeUInt32(stream, quint32(entry.data.size()));
        writeUInt32(stream, quint32(entry.data.size()));
        writeUInt16(stream, quint16(name.size()));
        writeUInt16(stream, 0);
        file.write(name);
        file.write(entry.data);
    }

    const quint32 directoryStart = quint32(file.pos());
    for (const ZipEntry &entry : entries) {
        const QByteArray name = entry.name.toUtf8();
        writeUInt32(stream, 0x02014b50);          // сигнатура записи каталога
        writeUInt16(stream, 20);
        writeUInt16(stream, 20);
        writeUInt16(stream, 0);
        writeUInt16(stream, 0);
        writeUInt16(stream, 0);
        writeUInt16(stream, 0);
        writeUInt32(stream, entry.crc);
        writeUInt32(stream, quint32(entry.data.size()));
        writeUInt32(stream, quint32(entry.data.size()));
        writeUInt16(stream, quint16(name.size()));
        writeUInt16(stream, 0);
        writeUInt16(stream, 0);
        writeUInt16(stream, 0);
        writeUInt16(stream, 0);
        writeUInt32(stream, 0);
        writeUInt32(stream, entry.offset);
        file.write(name);
    }
    const quint32 directorySize = quint32(file.pos()) - directoryStart;

    writeUInt32(stream, 0x06054b50);              // конец каталога
    writeUInt16(stream, 0);
    writeUInt16(stream, 0);
    writeUInt16(stream, quint16(entries.size()));
    writeUInt16(stream, quint16(entries.size()));
    writeUInt32(stream, directorySize);
    writeUInt32(stream, directoryStart);
    writeUInt16(stream, 0);

    file.close();
    return true;
}

}  // namespace

void Document::addHeading(const QString &text, int level) {
    // Размер в полупунктах: заголовки крупнее обычного текста
    const int size = level == 0 ? 36 : (level == 1 ? 28 : 24);
    m_body += QStringLiteral(
                  "<w:p><w:pPr><w:spacing w:before=\"240\" w:after=\"120\"/>"
                  "</w:pPr><w:r><w:rPr><w:b/><w:sz w:val=\"%1\"/></w:rPr>"
                  "<w:t xml:space=\"preserve\">%2</w:t></w:r></w:p>")
                  .arg(size)
                  .arg(escape(text));
}

void Document::addParagraph(const QString &text) {
    m_body += QStringLiteral("<w:p><w:r><w:t xml:space=\"preserve\">%1</w:t>"
                             "</w:r></w:p>")
                  .arg(escape(text));
}

void Document::addBullet(const QString &text) {
    m_body += QStringLiteral(
                  "<w:p><w:pPr><w:ind w:left=\"360\"/></w:pPr><w:r>"
                  "<w:t xml:space=\"preserve\">— %1</w:t></w:r></w:p>")
                  .arg(escape(text));
}

void Document::addTable(const QStringList &headers,
                        const QVector<QStringList> &rows) {
    QString table = QStringLiteral(
        "<w:tbl><w:tblPr><w:tblW w:w=\"5000\" w:type=\"pct\"/>"
        "<w:tblBorders>"
        "<w:top w:val=\"single\" w:sz=\"4\" w:color=\"999999\"/>"
        "<w:left w:val=\"single\" w:sz=\"4\" w:color=\"999999\"/>"
        "<w:bottom w:val=\"single\" w:sz=\"4\" w:color=\"999999\"/>"
        "<w:right w:val=\"single\" w:sz=\"4\" w:color=\"999999\"/>"
        "<w:insideH w:val=\"single\" w:sz=\"4\" w:color=\"999999\"/>"
        "<w:insideV w:val=\"single\" w:sz=\"4\" w:color=\"999999\"/>"
        "</w:tblBorders></w:tblPr>");

    table += "<w:tr>";
    for (const QString &header : headers) {
        table += QStringLiteral(
                     "<w:tc><w:tcPr><w:tcW w:w=\"0\" w:type=\"auto\"/></w:tcPr>"
                     "<w:p><w:r><w:rPr><w:b/></w:rPr>"
                     "<w:t xml:space=\"preserve\">%1</w:t></w:r></w:p></w:tc>")
                     .arg(escape(header));
    }
    table += "</w:tr>";

    for (const QStringList &row : rows) {
        table += "<w:tr>";
        for (const QString &cell : row) {
            table += QStringLiteral(
                         "<w:tc><w:tcPr><w:tcW w:w=\"0\" w:type=\"auto\"/>"
                         "</w:tcPr><w:p><w:r>"
                         "<w:t xml:space=\"preserve\">%1</w:t></w:r></w:p></w:tc>")
                         .arg(escape(cell));
        }
        table += "</w:tr>";
    }
    table += "</w:tbl><w:p/>";
    m_body += table;
}

void Document::addImage(const QByteArray &png, double widthPt,
                        double heightPt) {
    m_images.append(png);
    const int number = m_images.size();
    // EMU — внутренняя единица OOXML, 12700 на пункт
    const qint64 width = qint64(widthPt * 12700);
    const qint64 height = qint64(heightPt * 12700);

    m_body += QStringLiteral(
                  "<w:p><w:r><w:drawing><wp:inline distT=\"0\" distB=\"0\" "
                  "distL=\"0\" distR=\"0\">"
                  "<wp:extent cx=\"%1\" cy=\"%2\"/>"
                  "<wp:docPr id=\"%3\" name=\"Рисунок %3\"/>"
                  "<a:graphic xmlns:a=\"http://schemas.openxmlformats.org/"
                  "drawingml/2006/main\">"
                  "<a:graphicData uri=\"http://schemas.openxmlformats.org/"
                  "drawingml/2006/picture\">"
                  "<pic:pic xmlns:pic=\"http://schemas.openxmlformats.org/"
                  "drawingml/2006/picture\">"
                  "<pic:nvPicPr><pic:cNvPr id=\"%3\" name=\"image%3.png\"/>"
                  "<pic:cNvPicPr/></pic:nvPicPr>"
                  "<pic:blipFill><a:blip r:embed=\"rId%3\"/>"
                  "<a:stretch><a:fillRect/></a:stretch></pic:blipFill>"
                  "<pic:spPr><a:xfrm><a:off x=\"0\" y=\"0\"/>"
                  "<a:ext cx=\"%1\" cy=\"%2\"/></a:xfrm>"
                  "<a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom></pic:spPr>"
                  "</pic:pic></a:graphicData></a:graphic>"
                  "</wp:inline></w:drawing></w:r></w:p>")
                  .arg(width)
                  .arg(height)
                  .arg(number);
}

bool Document::save(const QString &path, QString *error) const {
    QVector<ZipEntry> entries;

    QString contentTypes = QStringLiteral(
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/"
        "content-types\">"
        "<Default Extension=\"rels\" ContentType=\"application/"
        "vnd.openxmlformats-package.relationships+xml\"/>"
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
        "<Default Extension=\"png\" ContentType=\"image/png\"/>"
        "<Override PartName=\"/word/document.xml\" ContentType=\"application/"
        "vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>"
        "</Types>");
    entries.append({"[Content_Types].xml", contentTypes.toUtf8()});

    QString rootRels = QStringLiteral(
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/"
        "relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/"
        "officeDocument/2006/relationships/officeDocument\" "
        "Target=\"word/document.xml\"/></Relationships>");
    entries.append({"_rels/.rels", rootRels.toUtf8()});

    QString documentRels = QStringLiteral(
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/"
        "relationships\">");
    for (int i = 0; i < m_images.size(); ++i) {
        documentRels += QStringLiteral(
                            "<Relationship Id=\"rId%1\" Type=\"http://"
                            "schemas.openxmlformats.org/officeDocument/2006/"
                            "relationships/image\" Target=\"media/image%1.png\"/>")
                            .arg(i + 1);
        entries.append({QStringLiteral("word/media/image%1.png").arg(i + 1),
                        m_images[i]});
    }
    documentRels += "</Relationships>";
    entries.append({"word/_rels/document.xml.rels", documentRels.toUtf8()});

    QString document = QStringLiteral(
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document "
        "xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/"
        "relationships\" "
        "xmlns:wp=\"http://schemas.openxmlformats.org/drawingml/2006/"
        "wordprocessingDrawing\"><w:body>");
    document += m_body;
    document += QStringLiteral(
        "<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/>"
        "<w:pgMar w:top=\"1134\" w:right=\"850\" w:bottom=\"1134\" "
        "w:left=\"1134\"/></w:sectPr></w:body></w:document>");
    entries.append({"word/document.xml", document.toUtf8()});

    return writeZip(path, entries, error);
}

}  // namespace docx
