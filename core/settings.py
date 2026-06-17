from __future__ import annotations

from pathlib import Path

from pydantic import EmailStr, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_PATH = Path(".env")


class MailConfig(BaseSettings):
    """SMTP credentials — loaded from .env or environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    smtp_server: str | None = Field(default="smtp.gmail.com")
    smtp_port: int = Field(default=465, ge=1, le=65535)
    sender_email: EmailStr
    sender_app_password: SecretStr | None
    goodnotes_email: EmailStr

    @field_validator("smtp_port", mode="before")
    @classmethod
    def port_must_be_valid(cls, v: object) -> object:
        if isinstance(v, str) and not v.isdigit():
            raise ValueError(f"smtp_port must be a valid integer, got: {v!r}")
        return v

    @classmethod
    def try_load(cls) -> "MailConfig | None":
        """
        Attempt to load credentials from .env.
        Returns None silently if required fields are missing.
        """
        try:
            return cls()
        except Exception:  # noqa: BLE001
            return None

    def save_to_env(self) -> None:
        """
        Persist current credentials to .env.
        Only overwrites keys managed by MailConfig; preserves all other lines.
        """
        new_values: dict[str, str] = {
            "SMTP_SERVER": self.smtp_server,
            "SMTP_PORT": str(self.smtp_port),
            "SENDER_EMAIL": str(self.sender_email),
            "SENDER_APP_PASSWORD": self.sender_app_password.get_secret_value(),
            "GOODNOTES_EMAIL": str(self.goodnotes_email),
        }

        existing_lines: list[str] = []
        if _ENV_PATH.exists():
            existing_lines = _ENV_PATH.read_text(encoding="utf-8").splitlines()

        managed_keys = set(new_values.keys())
        kept_lines = [
            line for line in existing_lines
            if not any(line.startswith(k + "=") for k in managed_keys)
            and line.strip() != ""
        ]

        new_lines = [f"{k}={v}" for k, v in new_values.items()]
        _ENV_PATH.write_text(
            "\n".join(kept_lines + new_lines) + "\n",
            encoding="utf-8",
        )


class GraderConfig(BaseSettings):
    """API credentials for the AI grader (Qwen-VL via Bailian)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        env_prefix="GRADER_",
    )

    api_key: SecretStr
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: str = "qwen3-vl-flash"
    dpi: int = Field(default=200, ge=72, le=600)
    enable_thinking: bool = False

    @classmethod
    def try_load(cls) -> "GraderConfig | None":
        try:
            return cls()
        except Exception:
            return None

    def save_to_env(self) -> None:
        new_values: dict[str, str] = {
            "GRADER_API_KEY": self.api_key.get_secret_value(),
            "GRADER_BASE_URL": self.base_url,
            "GRADER_MODEL": self.model,
        }

        existing_lines: list[str] = []
        if _ENV_PATH.exists():
            existing_lines = _ENV_PATH.read_text(encoding="utf-8").splitlines()

        managed_keys = set(new_values.keys())
        kept_lines = [
            line for line in existing_lines
            if not any(line.startswith(k + "=") for k in managed_keys)
            and line.strip() != ""
        ]

        new_lines = [f"{k}={v}" for k, v in new_values.items()]
        _ENV_PATH.write_text(
            "\n".join(kept_lines + new_lines) + "\n",
            encoding="utf-8",
        )


class AppSettings(BaseSettings):
    """Application-level path configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    base_dir: Path = Path.home() / ".cie_helper"

    @property
    def pdfs_dir(self) -> Path:
        return self.base_dir / "pdfs"

    @property
    def data_csv(self) -> Path:
        return self.base_dir / "data.csv"

    def init_dirs(self) -> None:
        """Create required directories if they don't exist."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.pdfs_dir.mkdir(parents=True, exist_ok=True)


# Module-level singleton — import this directly in other modules
app_settings = AppSettings()