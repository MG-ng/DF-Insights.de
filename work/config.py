import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _get_int(name, default):
    value = os.getenv(name)
    if value is None:
        return default

    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer, got {value!r}") from error


def _get_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default

    normalized_value = value.strip().lower()
    if normalized_value in {"1", "true", "yes", "on"}:
        return True
    if normalized_value in {"0", "false", "no", "off"}:
        return False

    raise ValueError(f"{name} must be a boolean, got {value!r}")


DB_PARAMS = {
    "host": os.getenv("DB_HOST", "localhost"),
    "database": os.getenv("DB_NAME", "smard_data"),
    "user": os.getenv("DB_USER", "remoteu"),
    "password": os.getenv("DB_PASSWORD") or os.getenv("DBP"),
    "port": _get_int("DB_PORT", 5432),
}

APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = _get_int("APP_PORT", 5000)
APP_DEBUG = _get_bool("APP_DEBUG", False)


def sqlalchemy_database_url():
    from sqlalchemy import URL

    return URL.create(
        drivername="postgresql+psycopg2",
        username=str(DB_PARAMS["user"]),
        password=str(DB_PARAMS["password"]),
        host=str(DB_PARAMS["host"]),
        port=int(DB_PARAMS["port"]),
        database=str(DB_PARAMS["database"]),
    )
