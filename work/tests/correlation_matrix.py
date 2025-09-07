import os
from typing import get_args, Literal

import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
import pandas as pd
from sqlalchemy import create_engine
import scipy
import dask.dataframe as dd

from psqlDatabase.openMeteoForecast import models

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


def processMatrix( matrix, name ):
	print("Correlation matrix is : ")
	print(matrix)
	plt.figure(figsize=(21, 20))  # small one only for Dunkelflauten data, big timeseries on Colab
	sns.heatmap(matrix, annot=True, cmap="coolwarm", fmt=".2f", center=0, linewidths=0.5)
	plt.savefig( f"plots/plot{name}.jpg",
				 dpi = 90,  # High resolution
				 bbox_inches = 'tight',  # Remove extra whitespace
				 format = 'jpg' )  # File format
	plt.close()  # Free memory

#
# for threshold in [ 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55 ]:
# 	name = round(threshold*100)
# 	dataframe = pd.read_sql(f"""
# 		SELECT *
# 			FROM computed_data_dunkelflauten_enriched{name};
# 	""", engine)
#
# 	for method in get_args( Literal[ 'kendall', 'pearson', 'spearman' ] ):
# 		matrix = dataframe.corr( method = method )
# 		processMatrix( matrix, "DF-" + str( name ) + "-" + method )

name = "All"

# dataframe = pd.read_sql(f"""
# 		SELECT *
# 		FROM smard_data_collection smard
# 		INNER JOIN computed_data_historical_weather_agg weather
# 			ON (EXTRACT(EPOCH FROM weather.date::timestamptz) * 1000)::bigint = smard.unix_timestamp_ms
# 		INNER JOIN computed_data_re_share_and_external_trade re  --TODO: Correct time zone in join - or redownload table in UTC
# 			ON (smard.unix_timestamp_ms=re.unix_timestamp_ms AND smard.region=re.region AND smard.resolution=re.resolution)
# 		WHERE smard.resolution='hour'
# 		AND weather.resolution='hour'
# 		AND smard.region='DE'
# 		AND smard.unix_timestamp_ms > 1704063600000  -- To reduce the size (1. Januar 2024 00:00:00 GMT+01:00)
# 		AND smard.unix_timestamp_ms < 1735686000000; --1. Januar 2025 00:00:00 GMT+01:00
# 	""", engine)

for model in models.values():
	dataframe = pd.read_sql(f"""
			SELECT smard.*, re.*,
			forecast.timestamp_s,
			forecast.direct_radiation_avg,
			forecast.direct_radiation_avg_previous_day1,
			forecast.direct_radiation_avg_previous_day2,
			forecast.direct_radiation_avg_previous_day3,
			forecast.diffuse_radiation_avg,
			forecast.diffuse_radiation_avg_previous_day1,
			forecast.diffuse_radiation_avg_previous_day2,
			forecast.diffuse_radiation_avg_previous_day3,
			forecast.temp2m_avg,
			forecast.wind_speed_80m_avg,
			forecast.wind_speed_80m_avg_previous_day1,
			forecast.wind_speed_80m_avg_previous_day2,
			forecast.wind_speed_80m_avg_previous_day3,
			forecast.wind_speed_120m_avg,
			forecast.wind_speed_120m_avg_previous_day1,
			forecast.wind_speed_120m_avg_previous_day2,
			forecast.wind_speed_120m_avg_previous_day3,
			forecast.wind_speed_180m_avg,
			forecast.wind_speed_180m_avg_previous_day1,
			forecast.wind_speed_180m_avg_previous_day2,
			forecast.wind_speed_180m_avg_previous_day3,
			forecast.wind_100m_log,
			forecast.wind_100m_log_previous_day1,
			forecast.wind_100m_log_previous_day2,
			forecast.wind_100m_log_previous_day3,
			forecast.repi_power1avg2,
			forecast.repi_power1avg2_previous_day1,
			forecast.repi_power1avg2_previous_day2,
			forecast.repi_power1avg2_previous_day3
			FROM smard_data_collection smard
			INNER JOIN computed_data_weather_forecasts_agg forecast
				ON (forecast.timestamp_s * 1000::bigint = smard.unix_timestamp_ms AND forecast.model='{model}')
			INNER JOIN computed_data_re_share_and_external_trade re
				ON (smard.unix_timestamp_ms=re.unix_timestamp_ms AND smard.region=re.region AND smard.resolution=re.resolution)
			WHERE smard.resolution='hour'
			AND forecast.temporal_resolution='hour'
			AND smard.region='DE'
		""", engine)


	numeric_df = dataframe.select_dtypes( include = [ np.number ] )
	dtypes = numeric_df.dtypes.to_dict()
	print( f"{dtypes = }" )

	# Get positions of columns with specific name
	indices = [i for i, col in enumerate(numeric_df.columns) if col == 'unix_timestamp_ms']
	# remove last one
	numeric_df = numeric_df.drop(numeric_df.columns[indices[-1]], axis=1)
	# Export
	numeric_df.to_hdf(f'data-{model}.h5', key='df', mode='w')


# pearson for linear relationships
# It can be revealing to look at the cases where they give very different values, especially where they differ in sign;
# it gives a better sense of the sorts of things they're each more sensitive to, for example if
# X = {1, 2, 3, 4, 5, 6, 7}
# Y = {2, 1, 7, 6, 5, 4, 3}
# then Spearman sees the correlation as positive (0.25) while Kendall sees it as negative (-0.0476)

#    +--+--------+--------+--------+---------+--------+--------+--+
#  7 +                    *                                       +
#    |                                                            |
#  6 +                             *                              +
#    |                                                            |
#  5 +                                       *                    +
#    |                                                            |
#  4 +                                                *           +
#    |                                                            |
#  3 +                                                         *  +
#    |                                                            |
#  2 +  *                                                         +
#    |                                                            |
#  1 +           *                                                +
#    +--+--------+--------+--------+---------+--------+--------+--+
#       1        2        3        4         5        6        7

# Import the exported H5 file for fast (~1min/img) matrix generation on a free Google Colab
# using the google_colab_code.py file

