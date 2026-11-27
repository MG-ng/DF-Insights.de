"""Export the hourly datasets for the Colab correlation notebook (tests/google_colab_code.py).

Writes into work/static/, so the website serves them:

- data.h5:          hourly SMARD values (DE) joined with the historical weather aggregates and the
                    renewable-share view (computed_data_re_share_and_external_trade)
- data-<model>.h5:  the same SMARD and renewable-share values joined with the previous-run
                    forecasts of one Open-Meteo model (computed_data_weather_forecasts_agg)

Each file is a pandas DataFrame under the key "df" (pd.read_hdf(path)), numeric columns only,
from --start (default 2024-01-01 UTC) up to the newest data. updateDatabase.py runs this after
every view refresh; it can also be run by hand:

    .venv/bin/python -u work/exportColabData.py
    .venv/bin/python -u work/exportColabData.py --start 2024-01-01 --end 2025-01-01

Based on the export in tests/correlation_matrix.py, which joined the weather in Berlin time;
the weather is stored as UTC instants now, so it is joined on the same instant as SMARD.
"""
import argparse
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

WORK_DIR = Path(__file__).resolve().parent
for path in (WORK_DIR, WORK_DIR / "psqlDatabase"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from config import sqlalchemy_database_url  # noqa: E402
from Helper import (TABLE_NAME_SMARD, VIEW_NAME_HISTORICAL_WEATHER_AGG, VIEW_NAME_RE_SHARE_EXT_TRADE,  # noqa: E402
                    VIEW_NAME_WEATHER_FORECASTS_AGG)
from openMeteoForecastInsertion import models  # noqa: E402


OUTPUT_DIR = WORK_DIR / "static"
DEFAULT_START = date(2024, 1, 1)
RE_SHARE_COLUMNS = ("sum_of_photovoltaic_wind_onshore_offshore_computed",
                    "share_of_photovoltaic_wind_onshore_offshore_computed",
                    "share_of_renewable_energies_computed",
                    "import_to_validate")
FORECAST_COLUMNS = (
    "timestamp_s",
    "direct_radiation_avg", "direct_radiation_avg_previous_day1", "direct_radiation_avg_previous_day2",
    "direct_radiation_avg_previous_day3",
    "diffuse_radiation_avg", "diffuse_radiation_avg_previous_day1", "diffuse_radiation_avg_previous_day2",
    "diffuse_radiation_avg_previous_day3",
    "temp2m_avg",
    "wind_speed_80m_avg", "wind_speed_80m_avg_previous_day1", "wind_speed_80m_avg_previous_day2",
    "wind_speed_80m_avg_previous_day3",
    "wind_speed_120m_avg", "wind_speed_120m_avg_previous_day1", "wind_speed_120m_avg_previous_day2",
    "wind_speed_120m_avg_previous_day3",
    "wind_100m_log", "wind_100m_log_previous_day1", "wind_100m_log_previous_day2", "wind_100m_log_previous_day3",
    "repi_power1avg2", "repi_power1avg2_previous_day3",
    "repi_power_exp", "repi_power_exp_previous_day1", "repi_power_exp_previous_day2", "repi_power_exp_previous_day3",
)


def _re_columns():
    return ", ".join(f"re.{column}" for column in RE_SHARE_COLUMNS)


def weather_query():
    return text(f"""
        SELECT smard.*, weather.*, {_re_columns()}
        FROM {TABLE_NAME_SMARD} smard
        INNER JOIN {VIEW_NAME_HISTORICAL_WEATHER_AGG} weather
            ON weather.date = to_timestamp(smard.unix_timestamp_ms / 1000.0)
        INNER JOIN {VIEW_NAME_RE_SHARE_EXT_TRADE} re
            ON smard.unix_timestamp_ms = re.unix_timestamp_ms AND smard.region = re.region
           AND smard.resolution = re.resolution
        WHERE smard.resolution = 'hour'
          AND weather.resolution = 'hour'
          AND smard.region = 'DE'
          AND smard.unix_timestamp_ms >= :start_ms
          AND smard.unix_timestamp_ms < :end_ms
        ORDER BY smard.unix_timestamp_ms
    """)  # nosec B608 # table and column names are constants of this module and Helper.py, values are bound


def forecast_query():
    forecast_columns = ", ".join(f"forecast.{column}" for column in FORECAST_COLUMNS)
    return text(f"""
        SELECT smard.*, {_re_columns()}, {forecast_columns}
        FROM {TABLE_NAME_SMARD} smard
        INNER JOIN {VIEW_NAME_WEATHER_FORECASTS_AGG} forecast
            ON forecast.timestamp_s * 1000::bigint = smard.unix_timestamp_ms AND forecast.model = :model
        INNER JOIN {VIEW_NAME_RE_SHARE_EXT_TRADE} re
            ON smard.unix_timestamp_ms = re.unix_timestamp_ms AND smard.region = re.region
           AND smard.resolution = re.resolution
        WHERE smard.resolution = 'hour'
          AND forecast.temporal_resolution = 'hour'
          AND smard.region = 'DE'
          AND smard.unix_timestamp_ms >= :start_ms
          AND smard.unix_timestamp_ms < :end_ms
        ORDER BY smard.unix_timestamp_ms
    """)  # nosec B608 # table and column names are constants of this module and Helper.py, values are bound


def write_hdf_atomically(dataframe, path):
    """Write next to the target and rename, so a download never sees a half-written file."""
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        dataframe.to_hdf(temporary, key="df", mode="w")
        os.chmod(temporary, 0o644)  # the web server's user must be able to read it
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def export_dataset(engine, query, parameters, path, log=print):
    dataframe = pd.read_sql(query, engine, params=parameters)
    numeric = dataframe.select_dtypes(include=[np.number])
    write_hdf_atomically(numeric, path)
    log(f"Exported {len(numeric)} rows x {len(numeric.columns)} columns to {path}")
    return len(numeric)


def _to_ms(day):
    return int(datetime.combine(day, datetime.min.time(), timezone.utc).timestamp() * 1000)


def export_colab_data(output_dir=OUTPUT_DIR, start=DEFAULT_START, end=None, engine=None, log=print):
    """Write data.h5 and one data-<model>.h5 per forecast model. Returns {file name: row count}."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    parameters = {"start_ms": _to_ms(start), "end_ms": _to_ms(end) if end else 2**62}
    own_engine = engine is None
    engine = engine or create_engine(sqlalchemy_database_url())
    try:
        rows = {"data.h5": export_dataset(engine, weather_query(), parameters, output_dir / "data.h5", log)}
        for model in models.values():
            name = f"data-{model}.h5"
            rows[name] = export_dataset(engine, forecast_query(), {**parameters, "model": model},
                                        output_dir / name, log)
        return rows
    finally:
        if own_engine:
            engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export the hourly datasets for the Colab notebook.")
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START, metavar="YYYY-MM-DD",
                        help=f"First UTC date (default {DEFAULT_START}).")
    parser.add_argument("--end", type=date.fromisoformat, metavar="YYYY-MM-DD",
                        help="UTC date to stop before (default: up to the newest data).")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help=f"Default: {OUTPUT_DIR}")
    arguments = parser.parse_args(argv)
    export_colab_data(arguments.output_dir, arguments.start, arguments.end)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
