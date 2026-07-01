from __future__ import annotations

import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, field_validator

from core.settings import MailConfig
from core.storage import CSVStore

_MAX_ATTACHMENT_BYTES: Final[int] = 10 * 1024 * 1024  # 10MB
# Some papers involve huge scans, so we cap the attachment size to avoid SMTP issues.


# ---------------------------------------------------------------------------
# Input / Result schemas
# ---------------------------------------------------------------------------


class MailRequest(BaseModel):
    """Validated input for a single mail job."""

    model_config = {"strict": True}

    paper_id: str
    qp_path: str

    @field_validator("paper_id")
    @classmethod
    def paper_id_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("paper_id cannot be empty")
        return v

    @field_validator("qp_path")
    @classmethod
    def qp_path_must_exist(cls, v: str) -> str:
        path = Path(v.strip())
        if not path.exists():
            raise ValueError(f"QP file not found on disk: {v!r}")
        if not path.suffix.lower() == ".pdf":
            raise ValueError(f"Expected a .pdf file, got: {v!r}")
        if path.stat().st_size == 0:
            raise ValueError(f"QP file is empty: {v!r}")
        if path.stat().st_size > _MAX_ATTACHMENT_BYTES:
            size_mb = path.stat().st_size / (1024 * 1024)
            raise ValueError(
                f"QP file is too large to email ({size_mb:.1f} MB). "
                f"Limit is {_MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB."
            )
        return str(path)


class MailResult(BaseModel):
    """Outcome of a mail attempt."""

    model_config = ConfigDict(strict=False)

    success: bool
    paper_id: str
    recipient: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Mailer class
# ---------------------------------------------------------------------------


class GoodNotesMailer:
    """
    Sends the QP PDF to a GoodNotes import email address via SMTP SSL,
    then marks sent_to_gn=True in the CSV store.
    """

    def __init__(self, config: MailConfig, store: CSVStore | None = None) -> None:
        self._config = config
        self._store = store or CSVStore()

    def send(self, request: MailRequest) -> MailResult:
        """
        Build and dispatch the email. Returns a MailResult — never raises
        on SMTP errors so Streamlit can handle display cleanly.
        """
        try:
            message = self._build_message(request)
            self._dispatch(message)
        except _MailError as exc:
            return MailResult(
                success=False,
                paper_id=request.paper_id,
                error=str(exc),
            )

        # Persist the sent_to_gn flag
        try:
            records = self._store.load_all()
            for record in records:
                if record.paper_id == request.paper_id:
                    updated = record.model_copy(update={"sent_to_gn": True})
                    self._store.update(updated)
                    break
            else:
                # Not a fatal error — email was sent, just flag the warning
                return MailResult(
                    success=True,
                    paper_id=request.paper_id,
                    recipient=str(self._config.goodnotes_email),
                    error=(
                        "Email sent but could not update sent_to_gn flag: "
                        f"paper_id '{request.paper_id}' not found in store."
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            return MailResult(
                success=True,
                paper_id=request.paper_id,
                recipient=str(self._config.goodnotes_email),
                error=f"Email sent but failed to update store: {exc}",
            )

        return MailResult(
            success=True,
            paper_id=request.paper_id,
            recipient=str(self._config.goodnotes_email),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_message(self, request: MailRequest) -> MIMEMultipart:
        """Construct the MIME email with the QP PDF attached."""
        msg = MIMEMultipart()
        msg["From"] = self._config.sender_email
        msg["To"] = str(self._config.goodnotes_email)
        msg["Subject"] = f"CIE Paper: {request.paper_id}"

        body = MIMEText(
            f"Past paper attached: {request.paper_id}\n\n"
            "Sent automatically by CIE Helper.",
            "plain",
        )
        msg.attach(body)

        qp_path = Path(request.qp_path)
        try:
            with qp_path.open("rb") as fh:
                attachment = MIMEApplication(fh.read(), _subtype="pdf")
        except OSError as exc:
            raise _MailError(f"Could not read QP file for attachment: {exc}") from exc

        attachment.add_header(
            "Content-Disposition",
            "attachment",
            filename=qp_path.name,
        )
        msg.attach(attachment)
        return msg

    def _dispatch(self, message: MIMEMultipart) -> None:
        """Open an SSL connection and send the message."""
        context = ssl.create_default_context()
        if self._config.sender_app_password is None:
            raise _MailError("No app password configured.")
        password = self._config.sender_app_password.get_secret_value()
        if self._config.smtp_server is None:
            raise _MailError("No SMTP server configured.")

        try:
            with smtplib.SMTP_SSL(
                self._config.smtp_server,
                self._config.smtp_port,
                context=context,
            ) as server:
                server.login(self._config.sender_email, password)
                server.sendmail(
                    self._config.sender_email,
                    str(self._config.goodnotes_email),
                    message.as_string(),
                )
        except smtplib.SMTPAuthenticationError as exc:
            raise _MailError(
                "SMTP authentication failed. Check your App Password and sender email."
            ) from exc
        except smtplib.SMTPConnectError as exc:
            server = f"{self._config.smtp_server}:{self._config.smtp_port}"
            raise _MailError(
                f"Could not connect to {server}. Check SMTP server and port."
            ) from exc
        except smtplib.SMTPException as exc:
            raise _MailError(f"SMTP error while sending: {exc}") from exc
        except OSError as exc:
            raise _MailError(f"Network error while sending email: {exc}") from exc


# ---------------------------------------------------------------------------
# Internal exception
# ---------------------------------------------------------------------------


class _MailError(Exception):
    """Raised internally when email sending fails. Never leaks outside this module."""
