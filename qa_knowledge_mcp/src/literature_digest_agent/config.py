from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parents[1]


def resolve_project_path(path: Path | str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


_DOTENV_LOADED = False
DEFAULT_DOTENV_PATH = PROJECT_ROOT / ".env"


def load_dotenv(path: str | Path | None = None) -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    env_path = Path(path) if path is not None else DEFAULT_DOTENV_PATH
    if not env_path.exists() and path is None:
        env_path = Path(".env")
    if not env_path.exists() or not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

    if "OPENAI_BASE_URL" not in os.environ and "OPENAI_API_BASE" in os.environ:
        os.environ["OPENAI_BASE_URL"] = os.environ["OPENAI_API_BASE"]


def env_str(name: str, default: str = "") -> str:
    load_dotenv()
    return os.environ.get(name, default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    raw = env_str(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int, lower: int | None = None, upper: int | None = None) -> int:
    raw = env_str(name)
    try:
        value = int(raw)
    except ValueError:
        value = default
    if lower is not None:
        value = max(lower, value)
    if upper is not None:
        value = min(upper, value)
    return value


@dataclass(frozen=True)
class HubSettings:
    base_url: str = ""
    timeout_seconds: int = 120


@dataclass(frozen=True)
class SmtpSettings:
    server: str
    port: int
    use_ssl: bool
    sender: str
    password: str
    recipients: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "SmtpSettings":
        recipients = tuple(
            item.strip()
            for item in env_str("EMAIL_TO").split(",")
            if item.strip()
        )
        return cls(
            server=env_str("SMTP_SERVER", "smtp.gmail.com"),
            port=env_int("SMTP_PORT", 587, 1, 65535),
            use_ssl=env_bool("SMTP_USE_SSL", False),
            sender=env_str("EMAIL_FROM"),
            password=env_str("EMAIL_PASSWORD"),
            recipients=recipients,
        )

    def is_complete(self) -> bool:
        return bool(self.server and self.sender and self.password and self.recipients)


@dataclass(frozen=True)
class RunSettings:
    hub: HubSettings
    digest_date: str
    discipline: str
    limit: int
    keywords_path: Path
    taxonomy_path: Path | None
    input_digest_path: Path | None
    output_path: Path | None
    enable_llm_classification: bool
    max_workers: int
    email: bool
    smtp: SmtpSettings

    @classmethod
    def from_env(cls) -> "RunSettings":
        taxonomy_raw = env_str("LDA_TAXONOMY_PATH")
        input_raw = env_str("LDA_INPUT_DIGEST_PATH")
        output_raw = env_str("LDA_OUTPUT_PATH")
        return cls(
            hub=HubSettings(
                base_url=env_str("LITERATURE_HUB_BASE_URL", "").rstrip("/"),
                timeout_seconds=env_int("LITERATURE_HUB_TIMEOUT_SECONDS", 120, 1, 1800),
            ),
            digest_date=env_str("LDA_DATE", date.today().isoformat()),
            discipline=env_str("LDA_DISCIPLINE", "cond-mat"),
            limit=env_int("LDA_LIMIT", 50, 1, 500),
            keywords_path=resolve_project_path(Path(env_str("LDA_KEYWORDS_PATH", "examples/literature_digest/keywords.json"))),
            taxonomy_path=(resolve_project_path(Path(taxonomy_raw)) if taxonomy_raw else None),
            input_digest_path=(resolve_project_path(Path(input_raw)) if input_raw else None),
            output_path=(resolve_project_path(Path(output_raw)) if output_raw else None),
            enable_llm_classification=env_bool("LDA_ENABLE_LLM_CLASSIFICATION", True),
            max_workers=env_int("LDA_MAX_WORKERS", 4, 1, 32),
            email=env_bool("LDA_EMAIL", False),
            smtp=SmtpSettings.from_env(),
        )


@dataclass(frozen=True)
class CatalogSettings:
    hub: HubSettings
    discipline: str
    fetch_limit: int
    keywords_path: Path
    taxonomy_path: Path | None
    enable_llm_classification: bool
    max_workers: int
    database_path: Path
    timezone: str
    cutoff_hour: int = 8

    @classmethod
    def from_env(cls) -> "CatalogSettings":
        run_settings = RunSettings.from_env()
        return cls(
            hub=run_settings.hub,
            discipline=run_settings.discipline,
            fetch_limit=env_int("LDA_DAILY_FETCH_LIMIT", 500, 1, 5000),
            keywords_path=resolve_project_path(run_settings.keywords_path),
            taxonomy_path=(
                resolve_project_path(run_settings.taxonomy_path)
                if run_settings.taxonomy_path
                else None
            ),
            enable_llm_classification=run_settings.enable_llm_classification,
            max_workers=run_settings.max_workers,
            database_path=resolve_project_path(
                Path(env_str("LDA_DATABASE_PATH", "data/literature_digest/literature_digest.sqlite3"))
            ),
            timezone=env_str("LDA_TIMEZONE", "Asia/Shanghai"),
            cutoff_hour=env_int("LDA_CUTOFF_HOUR", 8, 0, 23),
        )
