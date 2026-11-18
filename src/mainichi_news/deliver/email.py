"""SMTP delivery (multipart/alternative: text + HTML)."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from ..config import Config, ConfigError
from ..models import Digest


class EmailDeliverer:
    name = "email"

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    @property
    def enabled(self) -> bool:
        return self.cfg.deliver.email_enabled

    def build_message(self, digest: Digest, subject: str, markdown: str, html: str) -> EmailMessage:
        cfg = self.cfg.deliver
        message = EmailMessage()
        message["Subject"] = f"{cfg.subject_prefix}{subject}"
        message["From"] = formataddr(("毎日ニュース", cfg.sender or cfg.smtp_user))
        message["To"] = cfg.to
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid(domain="mainichi-news.local")
        message.set_content(markdown)
        message.add_alternative(html, subtype="html")
        return message

    def send(self, digest: Digest, subject: str, markdown: str, html: str) -> str:
        cfg = self.cfg.deliver
        if not cfg.email_enabled:
            raise ConfigError("SMTP_HOST と送信先(to)を設定してください")
        if not cfg.smtp_user or not cfg.smtp_password:
            raise ConfigError("SMTP_USER / SMTP_PASSWORD が未設定です")

        message = self.build_message(digest, subject, markdown, html)
        context = ssl.create_default_context()
        try:
            if cfg.smtp_port == 465:
                with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=30, context=context) as smtp:
                    smtp.login(cfg.smtp_user, cfg.smtp_password)
                    smtp.send_message(message)
            else:
                with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
                    smtp.ehlo()
                    if cfg.smtp_starttls:
                        smtp.starttls(context=context)
                        smtp.ehlo()
                    smtp.login(cfg.smtp_user, cfg.smtp_password)
                    smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise ConfigError(f"メール送信に失敗: {exc}") from exc
        return f"email:{cfg.to}"
