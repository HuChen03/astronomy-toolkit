from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import SmtpSettings


def send_html_email(settings: SmtpSettings, subject: str, html: str) -> bool:
    if not settings.is_complete():
        print("email skipped: EMAIL_FROM, EMAIL_PASSWORD, and EMAIL_TO are required")
        return False

    message = MIMEMultipart()
    message["Subject"] = subject
    message["From"] = settings.sender
    message["To"] = ", ".join(settings.recipients)
    message.attach(MIMEText(html, "html", "utf-8"))

    if settings.port == 465 or settings.use_ssl:
        server = smtplib.SMTP_SSL(settings.server, settings.port)
    else:
        server = smtplib.SMTP(settings.server, settings.port)
        server.starttls()
    try:
        server.login(settings.sender, settings.password)
        server.send_message(message)
        return True
    finally:
        server.quit()
