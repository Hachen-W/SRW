#include "logindialog.h"

#include <QFormLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QPushButton>
#include <QVBoxLayout>

#include "config.h"
#include "service.h"

LoginDialog::LoginDialog(QWidget *parent) : QDialog(parent) {
    setWindowTitle(QStringLiteral("Вход в сервис"));
    setMinimumWidth(360);

    m_username = new QLineEdit(service::sessionUsername());
    m_username->setPlaceholderText(QStringLiteral("логин"));
    m_email = new QLineEdit();
    m_email->setPlaceholderText(QStringLiteral("нужен только для регистрации"));
    m_password = new QLineEdit(service::sessionPassword());
    m_password->setEchoMode(QLineEdit::Password);

    auto *form = new QFormLayout();
    form->addRow(QStringLiteral("Логин"), m_username);
    form->addRow(QStringLiteral("Пароль"), m_password);
    form->addRow(QStringLiteral("Почта"), m_email);

    m_signInButton = new QPushButton(QStringLiteral("Войти"));
    m_signInButton->setDefault(true);
    connect(m_signInButton, &QPushButton::clicked, this, &LoginDialog::signIn);

    m_registerButton = new QPushButton(QStringLiteral("Зарегистрироваться"));
    connect(m_registerButton, &QPushButton::clicked, this,
            &LoginDialog::registerUser);

    auto *cancelButton = new QPushButton(QStringLiteral("Отмена"));
    connect(cancelButton, &QPushButton::clicked, this, &QDialog::reject);

    auto *buttons = new QHBoxLayout();
    buttons->addWidget(m_signInButton);
    buttons->addWidget(m_registerButton);
    buttons->addStretch();
    buttons->addWidget(cancelButton);

    m_status = new QLabel(QStringLiteral("Сервис: %1").arg(config::authUrl()));
    m_status->setWordWrap(true);

    auto *layout = new QVBoxLayout();
    layout->addLayout(form);
    layout->addLayout(buttons);
    layout->addWidget(m_status);
    setLayout(layout);
}

QString LoginDialog::username() const {
    return m_username->text().trimmed();
}

void LoginDialog::setBusy(bool busy) {
    m_signInButton->setEnabled(!busy);
    m_registerButton->setEnabled(!busy);
}

void LoginDialog::showError(const QString &text) {
    m_status->setText(text);
}

void LoginDialog::signIn() {
    const QString user = username();
    const QString password = m_password->text();
    if (user.isEmpty() || password.isEmpty()) {
        showError(QStringLiteral("Заполните логин и пароль"));
        return;
    }

    setBusy(true);
    m_status->setText(QStringLiteral("Вход..."));

    QString error;
    QString role;
    const bool ok = service::signIn(user, password, &role, &error);
    setBusy(false);

    if (!ok) {
        showError(error);
        return;
    }
    m_role = role;
    accept();
}

void LoginDialog::registerUser() {
    const QString user = username();
    const QString password = m_password->text();
    const QString email = m_email->text().trimmed();
    if (user.isEmpty() || password.isEmpty() || email.isEmpty()) {
        showError(QStringLiteral("Для регистрации нужны логин, пароль и почта"));
        return;
    }

    setBusy(true);
    m_status->setText(QStringLiteral("Регистрация..."));

    QString error;
    if (!service::registerUser(user, email, password, &error)) {
        setBusy(false);
        showError(error);
        return;
    }

    // Сразу входим под новой учётной записью
    QString role;
    const bool ok = service::signIn(user, password, &role, &error);
    setBusy(false);

    if (!ok) {
        showError(QStringLiteral("Пользователь создан, но вход не удался: %1")
                      .arg(error));
        return;
    }
    m_role = role;
    accept();
}
