"""Bring an existing database up to date without rebuilding it.

Fetches only what is new since the last run and refreshes the materialized views:

1. SMARD: for every raw filter and resolution, the newest buckets (the one holding the
   newest stored value, every newer one and one older one, because SMARD revises recent
   values). Values are upserted, so running it twice changes nothing.
2. Open-Meteo historical weather: from three days before the newest complete hour to today.
3. Open-Meteo previous-run forecasts: per model, from four days before the newest stored hour to today.
4. All materialized views, refreshed CONCURRENTLY where possible so the website keeps working.
5. The Colab datasets static/data.h5 and static/data-<model>.h5 (exportColabData.py).

The database must have been set up once with databaseSetupAll.py. Meant to run on a timer
(see .github/deploy/df-insights-update.timer), but can also be run by hand:

    .venv/bin/python -u work/updateDatabase.py
    .venv/bin/python -u work/updateDatabase.py --only smard --skip-views
    .venv/bin/python -u work/updateDatabase.py --since 2026-06-01   # refetch everything from this date

All times are UTC.
"""
import argparse
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

WORK_DIR = Path(__file__).resolve().parent
# The import modules use flat imports (from Helper import ..., from QuerySimple import ...)
for path in (WORK_DIR, WORK_DIR / "psqlDatabase"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import psycopg2  # noqa: E402

from config import DB_PARAMS  # noqa: E402
from Helper import TABLE_NAME_FORECASTS, TABLE_NAME_OPEN_METEO, TABLE_NAME_SMARD  # noqa: E402


SOURCES = ("smard", "weather", "forecast")
LOCK_ID = 0x0DF1_05E7  # pg_advisory_lock key: only one update at a time per database
WEATHER_OVERLAP = timedelta(days=3)    # archive data for the last days is still being filled in
FORECAST_OVERLAP = timedelta(days=4)   # previous_day1..3 of an hour arrive up to three days later


def log(message):
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{timestamp}] {message}", flush=True)


def table_exists(connection, table_name):
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s) IS NOT NULL", (table_name,))
        return cursor.fetchone()[0]


def utc_today():
    return datetime.now(timezone.utc).date()


def weather_start_date(connection, since):
    """First date to fetch again, or None when the table is empty."""
    if since is not None:
        return since
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT MAX(date) FROM {TABLE_NAME_OPEN_METEO} "  # nosec B608 # table name is a Helper.py constant
            "WHERE wind_speed_100m IS NOT NULL AND direct_radiation IS NOT NULL"
        )
        newest = cursor.fetchone()[0]
    if newest is None:
        return None
    return (newest.astimezone(timezone.utc) - WEATHER_OVERLAP).date()


def forecast_start_date(connection, model, since):
    if since is not None:
        return since
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT MAX(timestamp_s) FROM {TABLE_NAME_FORECASTS} "  # nosec B608 # table name is a Helper.py constant
            "WHERE model = %s AND temperature_2m IS NOT NULL",
            (model,),
        )
        newest = cursor.fetchone()[0]
    if newest is None:
        return None
    return (datetime.fromtimestamp(int(newest), timezone.utc) - FORECAST_OVERLAP).date()


def update_smard(connection, since):
    from smardDataInsertion import update_recent_smard_data

    if not table_exists(connection, TABLE_NAME_SMARD):
        raise RuntimeError(f"Table {TABLE_NAME_SMARD} does not exist. Run databaseSetupAll.py first.")
    since_ms = None
    if since is not None:
        since_ms = int(datetime.combine(since, datetime.min.time(), timezone.utc).timestamp() * 1000)
    written = update_recent_smard_data(connection, since_ms=since_ms, log=log)
    log(f"SMARD: {written} values written.")
    return written


def update_weather(connection, since, today):
    from openMeteoDataInsertion import create_engine_from_config, create_openmeteo_client, import_historical_range

    if since is None and not table_exists(connection, TABLE_NAME_OPEN_METEO):  # with --since, to_sql creates it
        raise RuntimeError(f"Table {TABLE_NAME_OPEN_METEO} does not exist. Run databaseSetupAll.py first.")
    start = weather_start_date(connection, since)
    if start is None:
        raise RuntimeError(f"{TABLE_NAME_OPEN_METEO} has no data yet. Run databaseSetupAll.py or pass --since.")
    if start > today:
        log("Historical weather: already up to date.")
        return 0
    log(f"Historical weather: fetching {start} to {today}.")
    # Short cache: the archive fills in the newest days over time, so they must be fetched again
    client = create_openmeteo_client("openmeteo_archive_update", expire_after=1800)
    engine = create_engine_from_config()
    try:
        written = import_historical_range(engine, client, start, today, verbose=False)
    finally:
        engine.dispose()
    log(f"Historical weather: {written} rows written.")
    return written


def update_forecasts(connection, since, today):
    from openMeteoDataInsertion import create_engine_from_config
    from openMeteoForecastInsertion import create_openmeteo_client, import_forecast_range, models

    if since is None and not table_exists(connection, TABLE_NAME_FORECASTS):  # with --since, to_sql creates it
        raise RuntimeError(f"Table {TABLE_NAME_FORECASTS} does not exist. Run databaseSetupAll.py first.")
    client = create_openmeteo_client("openmeteo_forecast_update", expire_after=1800)
    engine = create_engine_from_config()
    written = 0
    try:
        for model in models.values():
            start = forecast_start_date(connection, model, since)
            if start is None:
                log(f"Forecasts {model}: no stored data yet, skipped. Pass --since to load it.")
                continue
            if start > today:
                log(f"Forecasts {model}: already up to date.")
                continue
            log(f"Forecasts {model}: fetching {start} to {today}.")
            model_rows = import_forecast_range(engine, client, model, start, today, verbose=False)
            log(f"Forecasts {model}: {model_rows} rows written.")
            written += model_rows
    finally:
        engine.dispose()
    return written


def refresh_views():
    from computedViews import create_or_refresh_all_views

    if not create_or_refresh_all_views(DB_PARAMS, concurrently=True):
        raise RuntimeError("Refreshing the materialized views failed.")


def export_datasets():
    from exportColabData import export_colab_data

    export_colab_data(log=log)


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description="Fetch the newest SMARD and Open-Meteo data and refresh the views.")
    parser.add_argument("--only", action="append", choices=SOURCES,
                        help="Update only this source (repeatable). Default: all.")
    parser.add_argument("--skip-views", action="store_true",
                        help="Do not refresh the materialized views (and do not export the datasets).")
    parser.add_argument("--skip-export", action="store_true", help="Do not write static/data*.h5.")
    parser.add_argument("--since", type=date.fromisoformat, metavar="YYYY-MM-DD",
                        help="Refetch everything from this UTC date on instead of from the newest stored data.")
    return parser.parse_args(argv)


def main(argv=None):
    arguments = parse_arguments(argv)
    sources = arguments.only or list(SOURCES)
    today = utc_today()
    started_at = time.monotonic()

    try:
        connection = psycopg2.connect(**DB_PARAMS, connect_timeout=10)
    except psycopg2.Error as error:
        log(f"Cannot connect to PostgreSQL: {error}")
        return 1

    failures = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,))
            if not cursor.fetchone()[0]:
                log("Another update is still running on this database; exiting.")
                return 0
        connection.commit()

        steps = {
            "smard": lambda: update_smard(connection, arguments.since),
            "weather": lambda: update_weather(connection, arguments.since, today),
            "forecast": lambda: update_forecasts(connection, arguments.since, today),
        }
        for source in sources:
            log(f"Updating {source} ...")
            try:
                steps[source]()
            except Exception as error:  # keep going: one unreachable API must not block the others
                connection.rollback()
                failures.append(source)
                log(f"Updating {source} failed: {error!r}")

        if not arguments.skip_views:
            log("Refreshing materialized views ...")
            try:
                refresh_views()
            except Exception as error:
                failures.append("views")
                log(f"{error!r}")
            # The export reads the views, so it only runs on fresh ones
            if not arguments.skip_export and "views" not in failures:
                log("Exporting the Colab datasets ...")
                try:
                    export_datasets()
                except Exception as error:
                    failures.append("export")
                    log(f"Exporting the datasets failed: {error!r}")
    finally:
        connection.close()  # also releases the advisory lock

    elapsed = time.monotonic() - started_at
    if failures:
        log(f"Update finished with errors in {', '.join(failures)} after {elapsed:.0f} s.")
        return 1
    log(f"Update completed in {elapsed:.0f} s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
