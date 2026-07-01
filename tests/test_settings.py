"""Tests for core.settings."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.settings import MailConfig


def test_mail_config_requires_sender_email() -> None:
    """sender_email must not have a default — its absence signals 'unconfigured'."""
    with pytest.raises(ValidationError):
        MailConfig(
            _env_file=None,
            sender_app_password="secret",
            goodnotes_email="student@import.goodnotes.com",
        )
