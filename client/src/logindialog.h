// Окно входа и регистрации в сервисе аутентификации.
#pragma once

#include <QDialog>

class QLabel;
class QLineEdit;
class QPushButton;

class LoginDialog : public QDialog {
    Q_OBJECT

public:
    explicit LoginDialog(QWidget *parent = nullptr);

    QString username() const;
    QString role() const { return m_role; }

private slots:
    void signIn();
    void registerUser();

private:
    void setBusy(bool busy);
    void showError(const QString &text);

    QLineEdit *m_username = nullptr;
    QLineEdit *m_email = nullptr;
    QLineEdit *m_password = nullptr;
    QPushButton *m_signInButton = nullptr;
    QPushButton *m_registerButton = nullptr;
    QLabel *m_status = nullptr;
    QString m_role;
};
