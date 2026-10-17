import os

from project_paths import PROJECT_ROOT


DEFAULT_MODEL_ENDPOINT = "http://localhost:11434/api/generate"
DEFAULT_MODEL_NAME = "gemma4:31b-cloud"

_environment_loaded = False


class SettingsError(RuntimeError):
    """Raised when a required setting is missing from the environment."""


def load_environment():
    """Load PROJECT_ROOT/.env once without overriding exported variables."""
    global _environment_loaded
    if _environment_loaded:
        return
    _environment_loaded = True
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def get_setting(name, default=None):
    load_environment()
    value = os.environ.get(name, "").strip()
    return value or default


def require_settings(*names):
    values = {name: get_setting(name) for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise SettingsError(
            "Missing required settings in .env or the environment: "
            + ", ".join(missing)
        )
    return values
