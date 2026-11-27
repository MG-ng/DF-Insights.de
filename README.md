# Dunkelflauten Insights

A Flask web app for exploring *Dunkelflauten* in Germany: periods with little
wind and little sunshine, when renewable generation drops while electricity
demand stays high. It combines electricity-market data from
[SMARD](https://www.smard.de/) with weather data from
[Open-Meteo](https://open-meteo.com/), stores both in PostgreSQL, and shows them
as interactive charts.

## Features

- **Time series chart** of generation, consumption, residual load, prices and
  weather variables, with selectable region and resolution (quarter-hour to year).
- **Variable moving average** on top of the time series.
- **Dunkelflaute search** that finds periods matching your thresholds.
- **Bubble chart** to compare Dunkelflauten by duration, intensity and other metrics.
- **Weather map** (embedded from ventusky.com) to look at the weather patterns behind an event.
- **Forecast view** based on Open-Meteo forecasts.
- **Dunkelflaute outlook** on `/prediction`: 15-day probabilities from three weather ensembles
  (ECMWF IFS, ECMWF AIFS, NOAA GEFS), weather regime outlook and an honest backtest.

## Project layout

```text
.env.example              Template for the local configuration
work/
  app.py                  Flask app and HTTP routes
  config.py               Reads .env (database and server settings)
  databaseSetupAll.py     Runs the full database setup, step by step
  computedViews.py        Builds the materialized views used by the website
  Helper.py               Filters, regions and resolutions shared by app and imports
  psqlDatabase/           Schema creation, SMARD/Open-Meteo import and SQL queries
  prediction/             Dunkelflaute forecast: data download, training/backtest, live ensemble outlook
  templates/              Jinja2 pages (index, features, usage, prediction, about)
  static/                 JavaScript, CSS and images
  requirements-dev.txt    Tools for tests and CI checks (pytest, ruff, pip-audit, bandit)
  tests/                  Exploration scripts and experiments (with their own requirements.txt)
  tests/automated/        Automated test suite (pytest)
.github/workflows/        CI checks, approval-gated deploy and the nightly production check
.github/deploy/           Server deploy script and its one-time setup (SETUP.md)
```

## Requirements

- Python 3.11 or newer (required by the pinned NumPy version)
- PostgreSQL, with an existing, empty database and a user that can create
  tables, types and materialized views in it
- Internet access to the SMARD and Open-Meteo APIs during the data import

## Setup

### 1. Install the Python dependencies

```shell
python3 -m venv .venv
.venv/bin/pip install -r work/requirements.txt
```

The exploratory scripts in `work/tests/` (plots, correlation matrices) also need
matplotlib and seaborn. They are kept out of the server's requirements; install
them with `.venv/bin/pip install -r work/tests/requirements.txt`.

### 2. Create the database

The setup scripts create the tables, but not the database itself. For example:

```shell
sudo -u postgres createuser --pwprompt remoteu
sudo -u postgres createdb --owner remoteu smard_data
```

### 3. Configure `.env`

Copy the template and fill in your PostgreSQL credentials:

```shell
cp .env.example .env
```

| Variable      | Default        | Purpose                                   |
|---------------|----------------|-------------------------------------------|
| `DB_HOST`     | `localhost`    | PostgreSQL host                           |
| `DB_PORT`     | `5432`         | PostgreSQL port                           |
| `DB_NAME`     | `smard_data`   | Database name                             |
| `DB_USER`     | `remoteu`      | Database user                             |
| `DB_PASSWORD` | none           | Database password (required)              |
| `APP_HOST`    | `127.0.0.1`    | Host for the Flask development server     |
| `APP_PORT`    | `5000`         | Port for the Flask development server     |
| `APP_DEBUG`   | `false`        | Flask debug mode (never enable in production) |
| `CSP_ENFORCE` | `false`        | `true` enforces the Content-Security-Policy; `false` only reports violations in the browser console |
| `APP_VERSION` | git commit     | Version shown in the page footer, e.g. `2c34313 2026-11-26`. Empty = short hash and date of the checked-out commit |

`.env` is read from the repository root and is ignored by git. Variables that
are already set in the shell take precedence over the file. The old `DBP`
variable is still accepted as a fallback for `DB_PASSWORD`.

### 4. Initialize the database

`work/databaseSetupAll.py` runs the whole setup as one sequential job:

| Stage                | What it does                                       |
|----------------------|----------------------------------------------------|
| `schema`             | Creates the SMARD table and PostgreSQL types       |
| `smard`              | Imports SMARD electricity-market data              |
| `historical-weather` | Imports historical Open-Meteo weather data         |
| `forecast-weather`   | Imports previous-run Open-Meteo forecasts          |
| `views`              | Creates the materialized views used by the website |

Each stage runs in its own process, so its memory is released before the next
one starts. A stage only starts after the previous one succeeded; if a stage
fails, the setup stops instead of building data on top of an incomplete import.
The first full import can take several hours, so run it in the background:

```shell
nohup .venv/bin/python -u work/databaseSetupAll.py > ~/database_setup.log 2>&1 &
tail -f ~/database_setup.log
```

To see the planned commands without touching the database:

```shell
.venv/bin/python work/databaseSetupAll.py --dry-run
```

If earlier stages are already complete, resume at a named stage:

```shell
.venv/bin/python -u work/databaseSetupAll.py --start-at historical-weather
```

Notes:

- Do not run the individual SMARD or Open-Meteo import scripts at the same time
  as the setup job.
- On a low-memory server, stop the web app (e.g. the Gunicorn service) during
  the initial import. If a stage is reported as killed by `SIGKILL`, check
  `dmesg` for an out-of-memory kill.
- API responses are cached in `work/.cache/`. If an earlier `sudo` run created
  that folder as root, give it back to your user before resuming:

  ```shell
  sudo chown -R "$USER":"$(id -gn)" work/.cache
  .venv/bin/python -u work/databaseSetupAll.py --start-at forecast-weather
  ```

## Dunkelflaute forecast

`/prediction` shows a 15-day Dunkelflaute outlook. The code is in `work/prediction/`:

| File | Purpose |
|------|---------|
| `features.py` | Model points and hourly weather to daily features (turbine power curve applied hourly) |
| `model.py` | Energy model at runtime: weather features to wind, solar, demand and renewable share |
| `live.py` | Fetches the ECMWF IFS, ECMWF AIFS and NOAA GEFS ensembles (Open-Meteo), cached 6 hours |
| `train.py` | Fits the model, runs the backtest, writes `model.json` and `backtest.json` |
| `fetch_training_data.py` | Downloads SMARD, ERA5, sea level pressure and archived forecasts to `prediction/data/` |

The website only needs the committed `model.json` and `backtest.json`, no database. To retrain
with the newest data (takes about an hour, mostly Open-Meteo rate limits; the downloaded data is
not committed):

```shell
cd work
python -m prediction.fetch_training_data
python -m prediction.train
```

Open-Meteo's free tier allows about 10,000 weighted requests per day. A full download uses most
of that; if it stops with a rate limit, run it again the next day: finished parts are cached.

## Running the app

### Development

The app imports its modules relative to `work/`, so start it from there:

```shell
cd work
../.venv/bin/python app.py
```

Then open <http://127.0.0.1:5000> (or the `APP_HOST`/`APP_PORT` you configured).

### Production

Use a WSGI server instead of the Flask development server, for example Gunicorn
(not part of `requirements.txt`):

```shell
.venv/bin/pip install gunicorn
cd work
../.venv/bin/gunicorn --bind 127.0.0.1:8000 app:app
```

Put a reverse proxy such as nginx in front of it for HTTPS and gzip compression.

## Tests and CI

The automated tests live in `work/tests/automated/` and run from `work/`:

```shell
.venv/bin/pip install -r work/requirements-dev.txt
cd work
../.venv/bin/pytest
```

Most tests need no database. The tests in `test_api_database.py` load a tiny
fixture dataset into the database configured by the `DB_*` variables, so point
them at an **empty test database**, never at the production one (they create
and truncate `smard_data_collection`). Without a reachable database these
tests are skipped.

GitHub Actions (`.github/workflows/ci.yml`) runs on every pull request and every
push to `main`:

| Job      | What it checks                                                               |
|----------|------------------------------------------------------------------------------|
| lint     | `ruff check` (syntax errors and pyflakes rules, see `work/ruff.toml`)        |
| security | `pip-audit` on both requirements files, `bandit` (reviewed false positives are marked inline with `# nosec` and a reason), `gitleaks` on the full git history |
| tests    | `pytest` against a PostgreSQL 16 service container                           |

### Deploy

When CI passes on `main`, the **Deploy** workflow (`.github/workflows/deploy.yml`)
waits for approval in the GitHub `production` environment. It then connects to
the server over SSH with a key that can only run `.github/deploy/deploy.sh`.
That script checks out the commit, installs the requirements, restarts Gunicorn,
checks the version in the page footer and rolls back if anything fails. A smoke
test of https://df-insights.de follows, and the **Production check** workflow
repeats it every night. The one-time server and GitHub setup is in
[`.github/deploy/SETUP.md`](.github/deploy/SETUP.md).

## Data sources and third-party libraries

- Electricity-market data: [SMARD](https://www.smard.de/) (Bundesnetzagentur)
- Weather data and forecasts: [Open-Meteo](https://open-meteo.com/)
- Charts: [Highcharts](https://www.highcharts.com/) (Highcharts Stock, loaded from
  the Highcharts CDN). Highcharts is **not** open source: it is free only for
  non-commercial use, and commercial use needs a paid license from Highsoft.
  See [Highcharts licensing](https://shop.highcharts.com/license). A move to an
  open-source chart library is being considered for this reason.
- UI helpers: Bootstrap, Tom Select and Toastify (loaded from jsDelivr)

## Support

Contact me via [LinkedIn](https://www.linkedin.com/in/markusgockel/). Ideas for future
features are welcome.

## Contributing

Contributions are welcome. Please open an issue or a pull request.

## License

No license has been chosen for this repository yet, and no warranties are
provided. Third-party libraries and data keep their own licenses and terms
(see above).

## Project status

Most planned features are implemented. Further functionality can be developed
on request.
