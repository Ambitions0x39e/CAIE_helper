from __future__ import annotations

from pathlib import Path

from pydantic import EmailStr, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_PATH = Path.home() / ".cie_helper" / ".env"


def _write_env(new_values: dict[str, str]) -> None:
    """Write *new_values* into .env, preserving every line it does not own."""
    existing: list[str] = []
    if _ENV_PATH.exists():
        existing = _ENV_PATH.read_text(encoding="utf-8").splitlines()

    kept = [
        line for line in existing
        if line.strip()
        and not any(line.startswith(k + "=") for k in new_values)
    ]
    written = [f"{k}={v}" for k, v in new_values.items()]
    _ENV_PATH.write_text(
        "\n".join(kept + written) + "\n", encoding="utf-8"
    )


class MailConfig(BaseSettings):
    """SMTP credentials — loaded from .env or environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_PATH),
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
    def try_load(cls) -> MailConfig | None:
        """
        Attempt to load credentials from .env.
        Returns None silently if required fields are missing.
        """
        try:
            return cls()
        except Exception:  # noqa: BLE001
            return None

    def save_to_env(self) -> None:
        """Persist the SMTP credentials to .env."""
        new_values: dict[str, str] = {
            "SMTP_SERVER": self.smtp_server or "smtp.gmail.com",
            "SMTP_PORT": str(self.smtp_port),
            "SENDER_EMAIL": str(self.sender_email),
            "SENDER_APP_PASSWORD": self.sender_app_password.get_secret_value()
            if self.sender_app_password
            else "",
            "GOODNOTES_EMAIL": str(self.goodnotes_email),
        }

        _write_env(new_values)


class GraderConfig(BaseSettings):
    """API credentials for the AI grader (Qwen-VL via Bailian)."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        env_prefix="GRADER_",
    )

    api_key: SecretStr
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: str = "qwen3.6-flash"
    dpi: int = Field(default=200, ge=72, le=600)
    enable_thinking: bool = False

    @classmethod
    def try_load(cls) -> GraderConfig | None:
        try:
            return cls()
        except Exception:
            return None

    def save_to_env(self) -> None:
        """Persist the grader credentials to .env."""
        new_values: dict[str, str] = {
            "GRADER_API_KEY": self.api_key.get_secret_value(),
            "GRADER_BASE_URL": self.base_url,
            "GRADER_MODEL": self.model,
        }

        _write_env(new_values)


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

    @property
    def ms_cache_dir(self) -> Path:
        return self.base_dir / ".cache" / "ms"

    @property
    def mistakes_csv(self) -> Path:
        """Backing file for the mistake notebook — see ``MistakeStore``."""
        return self.base_dir / "mistakes.csv"

    @property
    def syllabus_dir(self) -> Path:
        """Parsed syllabus topic lists, one JSON per subject id.

        Deliberately *not* under ``.cache``: re-deriving one costs the user
        another manual PDF hunt and upload, so this is durable data that a
        cache sweep must not take with it.
        """
        return self.base_dir / "syllabus"

    @property
    def legacy_syllabus_cache_dir(self) -> Path:
        """Where parsed syllabuses lived before they moved out of ``.cache``.

        Read-and-migrate only — see ``syllabus_parser.load_syllabus``.
        """
        return self.base_dir / ".cache" / "syllabus"

    @property
    def updates_dir(self) -> Path:
        """Where downloaded app installers land before being handed to the OS."""
        return self.base_dir / "updates"

    def init_dirs(self) -> None:
        """Create required directories if they don't exist."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.pdfs_dir.mkdir(parents=True, exist_ok=True)
        self.ms_cache_dir.mkdir(parents=True, exist_ok=True)
        self.syllabus_dir.mkdir(parents=True, exist_ok=True)
        self.updates_dir.mkdir(parents=True, exist_ok=True)


# Module-level singleton — import this directly in other modules
app_settings = AppSettings()