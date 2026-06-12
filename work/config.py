import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv


WORK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WORK_DIR.parent
REQUEST_CACHE_DIR = WORK_DIR / ".cache"
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


def create_cached_http_session(cache_name, expire_after):
    import requests
    import requests_cache

    cache_path = REQUEST_CACHE_DIR / cache_name
    database_path = cache_path.with_suffix(".sqlite")
    try:
        REQUEST_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if not os.access(REQUEST_CACHE_DIR, os.W_OK):
            raise PermissionError(f"directory is not writable: {REQUEST_CACHE_DIR}")
        if database_path.exists() and not os.access(database_path, os.W_OK):
            raise PermissionError(f"database is not writable: {database_path}")
        return requests_cache.CachedSession(
            str(cache_path),
            expire_after=expire_after,
        )
    except (OSError, sqlite3.Error) as error:
        print(
            f"Warning: HTTP cache {cache_path}.sqlite is unavailable: {error}. "
            "Continuing without a persistent cache. Check the ownership of "
            f"{REQUEST_CACHE_DIR}.",
            flush=True,
        )
        return requests.Session()


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
