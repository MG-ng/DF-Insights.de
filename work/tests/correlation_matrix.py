import os
from typing import get_args

import seaborn as sns
import matplotlib.pyplot as plt
import pandas as pd
from jinja2.nodes import Literal
from sqlalchemy import create_engine
import scipy

# Check Data Type: Use Pearson for continuous data that is normally distributed. Use Spearman or Kendall for ordinal data or non-normally distributed data.
# Consider Assumptions: If your data is not normally distributed, or you suspect a non-linear relationship, choose Spearman or Kendall.
# Evaluate Sensitivity to Outliers: If you have outliers, Spearman or Kendall are better choices.

envPassword = os.getenv( 'DBP' )
db_host = os.getenv( 'DB_HOST', 'localhost' )
DB_PARAMS = {
    'host': db_host,
    'database': 'smard_data',
    'user': 'remoteu',
    'password': envPassword,
    'port': 5432
}

engine = create_engine('postgresql://' + DB_PARAMS["user"] + ':' + DB_PARAMS["password"] +
					   '@' + str(DB_PARAMS["host"]) + ':' + str(DB_PARAMS["port"]) + '/' + DB_PARAMS["database"])

def processMatrix( matrix, name, big=False ):
	print("Correlation matrix is : ")
	print(matrix)
	if big:
		plt.figure(figsize=(42, 40))  # Width, height in inches
	else:
		plt.figure(figsize=(21, 20))
	sns.heatmap(matrix, annot=True, cmap="coolwarm", fmt=".2f", center=0, linewidths=0.5)
	plt.title("Correlation Heatmap")
	plt.savefig( f"plots/plot{name}.jpg",
				 dpi = 90,  # High resolution
				 bbox_inches = 'tight',  # Remove extra whitespace
				 format = 'jpg' )  # File format

	plt.close()  # Free memory

for threshold in [ 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55 ]:
	# dataframe = pd.DataFrame(data=dataset.data, columns=dataset.feature_names)
	name = round(threshold*100)
	dataframe = pd.read_sql(f"""
		SELECT * 
			FROM computed_data_dunkelflauten_enriched{name};
	""", engine)

	for method in get_args( Literal[ 'kendall', 'pearson', 'spearman' ] ):
		matrix = dataframe.corr( method = method )
		processMatrix( matrix, str( name ) + "-" + method )

name = "All"
dataframe = pd.read_sql(f"""
		SELECT *
		FROM smard_data_collection smard
		INNER JOIN computed_data_historical_weather_agg weather
			ON (EXTRACT(EPOCH FROM weather.date::timestamptz) * 1000)::bigint = smard.unix_timestamp_ms
		INNER JOIN computed_data_re_share_and_external_trade re
			ON (smard.unix_timestamp_ms=re.unix_timestamp_ms AND smard.region=re.region AND smard.resolution=re.resolution)
		WHERE smard.resolution='hour'
		AND weather.resolution='hour'
		AND smard.region='DE'
		AND smard.market_price_ger_lux IS NOT NULL;  -- To reduce the size
	""", engine)


for method in get_args( Literal['kendall', 'pearson', 'spearman'] ):
	matrix = dataframe.corr(method=method)
	processMatrix( matrix, str(name) + "-" + method, big=True )

