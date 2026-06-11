import argparse
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psycopg2

from config import DB_PARAMS, PROJECT_ROOT, WORK_DIR


PSQL_DATABASE_DIR = WORK_DIR / "psqlDatabase"


@dataclass(frozen=True)
class SetupStep:
    name: str
    description: str
    script: Path


SETUP_STEPS = (
    SetupStep("schema", "Create the SMARD table and PostgreSQL types", PSQL_DATABASE_DIR / "databaseSetup.py"),
    SetupStep("smard", "Import SMARD electricity-market data", PSQL_DATABASE_DIR / "smardDataInsertion.py"),
    SetupStep(
        "historical-weather",
        "Import historical Open-Meteo data",
        PSQL_DATABASE_DIR / "openMeteoDataInsertion.py",
    ),
    SetupStep(
        "forecast-weather",
        "Import previous-run Open-Meteo forecasts",
        PSQL_DATABASE_DIR / "openMeteoForecastInsertion.py",
    ),
    SetupStep("views", "Create the materialized views used by the website", WORK_DIR / "computedViews.py"),
)


def log(message):
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"[{timestamp}] {message}", flush=True)


def child_environment():
    environment = os.environ.copy()
    python_paths = [str(WORK_DIR), str(PSQL_DATABASE_DIR)]
    if environment.get("PYTHONPATH"):
        python_paths.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


def verify_database_connection():
    connection = psycopg2.connect(**DB_PARAMS, connect_timeout=10)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database();")
            database_name = cursor.fetchone()[0]
        log(f"Connected to PostgreSQL database {database_name!r}.")
    finally:
        connection.close()


def selected_steps(start_at):
    start_index = next(index for index, step in enumerate(SETUP_STEPS) if step.name == start_at)
    return SETUP_STEPS[start_index:]


def run_step(step, position, total, environment, dry_run):
    command = [sys.executable, "-u", str(step.script)]
    log(f"[{position}/{total}] {step.description}")
    log(f"Running: {' '.join(command)}")

    if dry_run:
        return True

    started_at = time.monotonic()
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
    )
    elapsed_seconds = time.monotonic() - started_at

    if result.returncode == 0:
        log(f"Completed {step.name!r} in {elapsed_seconds:.1f} seconds.")
        return True

    if result.returncode < 0:
        signal_number = -result.returncode
        try:
            signal_name = signal.Signals(signal_number).name
        except ValueError:
            signal_name = f"signal {signal_number}"
        detail = f"killed by {signal_name}"
        if signal_number == signal.SIGKILL:
            detail += "; check dmesg for an out-of-memory kill"
    else:
        detail = f"exited with status {result.returncode}"

    log(f"Setup stopped: step {step.name!r} {detail}.")
    return False


def parse_arguments():
    step_names = [step.name for step in SETUP_STEPS]
    parser = argparse.ArgumentParser(
        description="Run all database initialization stages sequentially to limit peak memory usage."
    )
    parser.add_argument(
        "--start-at",
        choices=step_names,
        default=step_names[0],
        help="Start at this stage when earlier stages are already complete.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the ordered commands without connecting to PostgreSQL or executing them.",
    )
    return parser.parse_args()


def main():
    arguments = parse_arguments()
    steps = selected_steps(arguments.start_at)

    for step in steps:
        if not step.script.is_file():
            log(f"Setup script does not exist: {step.script}")
            return 1

    log("Database setup runs one child process at a time.")
    log("Each stage starts only after its dependency completed successfully.")
    log("Do not run the individual import scripts concurrently with this command.")

    if not arguments.dry_run:
        try:
            verify_database_connection()
        except psycopg2.Error as error:
            log(f"Cannot connect to PostgreSQL: {error}")
            return 1

    environment = child_environment()
    for position, step in enumerate(steps, start=1):
        if not run_step(step, position, len(steps), environment, arguments.dry_run):
            return 1

    if arguments.dry_run:
        log("Dry run completed.")
    else:
        log("Database setup completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
