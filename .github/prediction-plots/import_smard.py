"""Fast SMARD import for the Prediction plots workflow.

Imports only what the Dunkelflauten views read: DE, quarter-hour resolution,
the generation and consumption columns of the renewable share and the DE/LU
price, from SMARD_FROM_MS on. Each weekly bucket is fetched once, several in
parallel, and stored with the same upsert as work/psqlDatabase/smardDataInsertion.py.
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import smardDataInsertion as smard
from Helper import FILTER, FilterTranslations, FLAG

NEEDED = [
	"Electricity_Production_Lignite", "Electricity_Production_Nuclear_Energy",
	"Electricity_Production_Wind_Offshore", "Electricity_Production_Hydropower",
	"Electricity_Production_Other_Conventional", "Electricity_Production_Other_Renewables",
	"Electricity_Production_Biomass", "Electricity_Production_Wind_Onshore",
	"Electricity_Production_Photovoltaics", "Electricity_Production_Hard_coal",
	"Electricity_Production_Pumped_storage", "Electricity_Production_Natural_gas",
	"Power_Consumption_Total", "Power_Consumption_Residual_load",
	"Electricity_Consumption_Pumped_storage", "Market_Price_GER_LUX",
]
RESOLUTION = "quarterhour"
FROM_MS = int(os.environ.get("SMARD_FROM_MS", "0"))
WORKERS = int(os.environ.get("SMARD_WORKERS", "8"))


def fetch_bucket(filter_id, timestamp):
	url = f"{smard.BASE_URL}/chart_data/{filter_id}/DE/{filter_id}_DE_{RESOLUTION}_{timestamp}.json"
	for attempt in range(5):
		try:
			return smard.fetch_json(url)["series"]
		except Exception as error:  # network hiccups: retry with backoff
			if attempt == 4:
				raise
			print(f"retry {url}: {error}", flush=True)
			time.sleep(2 ** attempt)


def main():
	columns = [column for _, column in smard.SMARD_FILTERS]
	started = time.time()
	for name in NEEDED:
		filter_id = FILTER[FilterTranslations.inverse[name]]
		column_index = columns.index(name)
		index = smard.fetch_json(f"{smard.BASE_URL}/chart_data/{filter_id}/DE/index_{RESOLUTION}.json")
		buckets = [t for t in index["timestamps"] if t >= FROM_MS]
		with ThreadPoolExecutor(WORKERS) as pool:
			series = list(pool.map(lambda t: fetch_bucket(filter_id, t), buckets))
		rows = [smard.data_row(ts, False, "DE", RESOLUTION, column_index, value)
				for bucket in series for ts, value in bucket if value is not None and value != FLAG]
		count = len(rows)
		smard.flush_rows(rows, name)  # also empties rows
		print(f"{name}: {len(buckets)} buckets, {count} values, {time.time() - started:.0f}s", flush=True)
	return 0


if __name__ == "__main__":
	sys.exit(main())
