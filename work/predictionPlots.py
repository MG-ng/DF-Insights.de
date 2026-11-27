"""Correlation heatmaps for the /prediction page.

For every Dunkelflaute threshold shown on /prediction, this reads the
materialized view computed_data_dunkelflauten_enriched<threshold> (built by
computedViews.py) and draws one heatmap per correlation method:

    static/images/plots/plot<threshold>-<method>.jpg   e.g. plot35-spearman.jpg

The images are committed to git, so every deploy ships them. Run this again
after a data import to refresh them:

    pip install -r work/tests/requirements.txt   # matplotlib and seaborn
    python work/predictionPlots.py

The GitHub workflow .github/workflows/prediction-plots.yml does the same on a
fresh database built from the public SMARD and Open-Meteo APIs.
"""
import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display needed, also on the server

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import seaborn as sns  # noqa: E402
from psycopg2 import sql  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

from config import WORK_DIR, sqlalchemy_database_url  # noqa: E402
from Helper import VIEW_NAME_DUNKELFLAUTEN_STATS  # noqa: E402


# Must match the options of the threshold selector in templates/prediction.html
THRESHOLDS = (25, 30, 35, 40, 45, 50, 55)
METHODS = ("pearson", "kendall", "spearman")
PLOT_DIR = WORK_DIR / "static" / "images" / "plots"


def plot_path(threshold, method, plot_dir=PLOT_DIR):
	return Path(plot_dir) / f"plot{threshold}-{method}.jpg"


def numeric_columns(dataframe):
	"""All columns as numbers: NUMERIC comes back as Decimal objects and booleans as bool."""
	converted = pd.DataFrame(index=dataframe.index)
	for column in dataframe.columns:
		values = dataframe[column]
		if values.dtype == bool:
			converted[column] = values.astype(int)
		else:
			numbers = pd.to_numeric(values, errors="coerce")
			if numbers.notna().any():
				converted[column] = numbers.astype(float)
	# Constant columns have no correlation and would only show empty rows
	return converted.loc[:, converted.nunique(dropna=True) > 1]


def save_heatmap(matrix, title, path):
	size = max(8, 0.6 * len(matrix.columns))
	plt.figure(figsize=(size + 1, size))
	sns.heatmap(matrix, annot=True, cmap="coolwarm", fmt=".2f", center=0, vmin=-1, vmax=1, linewidths=0.5)
	plt.title(title, fontsize=16)
	plt.savefig(path, dpi=90, bbox_inches="tight", format="jpg")
	plt.close()


def generate(engine, thresholds=THRESHOLDS, methods=METHODS, plot_dir=PLOT_DIR):
	Path(plot_dir).mkdir(parents=True, exist_ok=True)
	written = []
	for threshold in thresholds:
		view = VIEW_NAME_DUNKELFLAUTEN_STATS + str(threshold)
		query = sql.SQL("SELECT * FROM {view} ORDER BY start_time;").format(view=sql.Identifier(view))
		with engine.connect() as connection:
			raw = connection.connection.dbapi_connection
			dataframe = pd.read_sql(query.as_string(raw), connection)
		numbers = numeric_columns(dataframe)
		print(f"{view}: {len(dataframe)} Dunkelflauten, {len(numbers.columns)} numeric columns")
		if len(dataframe) < 3 or len(numbers.columns) < 2:
			raise RuntimeError(f"{view} has too little data for a correlation matrix ({len(dataframe)} rows)")
		for method in methods:
			matrix = numbers.corr(method=method)
			path = plot_path(threshold, method, plot_dir)
			title = (f"{method.capitalize()} correlation, Dunkelflauten with at most {threshold}% renewables "
					 f"(n={len(dataframe)})")
			save_heatmap(matrix, title, path)
			written.append(path)
			print(f"  wrote {path}")
	return written


def main(argv=None):
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	parser.add_argument("--threshold", type=int, action="append", choices=THRESHOLDS,
						help="only this threshold (repeatable), default: all")
	parser.add_argument("--output", type=Path, default=PLOT_DIR, help=f"default: {PLOT_DIR}")
	args = parser.parse_args(argv)
	engine = create_engine(sqlalchemy_database_url())
	generate(engine, tuple(args.threshold or THRESHOLDS), METHODS, args.output)
	return 0


if __name__ == "__main__":
	sys.exit(main())
