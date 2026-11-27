import openmeteo_requests

import pandas as pd
from retry_requests import retry
from sqlalchemy import create_engine, inspect, text

from config import create_cached_http_session, sqlalchemy_database_url

from Helper import TABLE_NAME_FORECASTS

# from sklearn.metrics import root_mean_squared_error

# rms = root_mean_squared_error(y_actual, y_predicted)


# ecmwf_ifs025 doesn't deliver anything regarding wind other than on 10m height
models = {
	21: 'icon_global',
	22: 'icon_eu',
 	3: 'gfs_global',  # GFS doesn't deliver anything for wind on 180m height
}


def replace_forecast_rows(engine, dataframe, model, start_timestamp, end_timestamp, clear_model_range):
	with engine.begin() as connection:
		if clear_model_range and inspect(connection).has_table(TABLE_NAME_FORECASTS):
			connection.execute(
				text(f"""
					DELETE FROM {TABLE_NAME_FORECASTS}
					WHERE timestamp_s >= :start_timestamp
					  AND timestamp_s < :end_timestamp
					  AND model = :model;
				"""),  # nosec B608 # table name is a Helper.py constant, values are bound parameters
				{
					"start_timestamp": start_timestamp,
					"end_timestamp": end_timestamp,
					"model": model,
				},
			)
		dataframe.to_sql(TABLE_NAME_FORECASTS, connection, if_exists="append", index=False)


""" 12 locations from NW to SE (top left to bottom right)
54, 7
54, 10
54, 13
52, 7
52, 10
52, 13
50, 7
50, 10
50, 13
48, 7
48, 10
48, 13
"""

url = "https://previous-runs-api.open-meteo.com/v1/forecast"
LATITUDES = [ 54, 54, 54, 52, 52, 52, 50, 50, 50, 48, 48, 48 ]
LONGITUDES = [ 7, 10, 13, 7, 10, 13, 7, 10, 13, 7, 10, 13 ]
# The order of these variables is the order of hourly.Variables(i) in the response
HOURLY_VARIABLES = [
	f"{variable}{suffix}"
	for variable in [ "temperature_2m", "wind_speed_10m", "wind_direction_10m", "direct_radiation",
					  "diffuse_radiation", "wind_speed_80m", "wind_speed_120m", "wind_speed_180m",
					  "wind_direction_80m", "wind_direction_120m", "wind_direction_180m" ]
	for suffix in [ "", "_previous_day1", "_previous_day2", "_previous_day3" ]
]


def create_openmeteo_client(cache_name="openmeteo_forecast", expire_after=3600):
	"""Open-Meteo API client with cache and retry on error."""
	cache_session = create_cached_http_session( cache_name, expire_after = expire_after )
	retry_session = retry( cache_session, retries = 5, backoff_factor = 0.2 )
	return openmeteo_requests.Client( session = retry_session )


def hourly_dataframe_from_response(response):
	hourly = response.Hourly()
	hourly_data = {  # unix seconds, to not confuse with dates with correct time zone
		"timestamp_s": range(hourly.Time(), hourly.TimeEnd(), hourly.Interval())
	}
	hourly_data["lat"] = response.Latitude()
	hourly_data["lng"] = response.Longitude()
	hourly_data["elevation"] = response.Elevation()
	hourly_data["model"] = models[ response.Model() ]
	hourly_data["temporal_resolution"] = "hour"
	for index, variable in enumerate( HOURLY_VARIABLES ):
		hourly_data[ variable ] = hourly.Variables( index ).ValuesAsNumpy()
	return pd.DataFrame( data = hourly_data )


def import_forecast_range(engine, openmeteo, model, start_date, end_date, verbose=True):
	"""Fetch previous-run forecasts of one model for [start_date, end_date] (inclusive dates, UTC)
	and replace that range of the model in the table. Returns the number of rows written."""
	params = {
		"latitude": LATITUDES,
		"longitude": LONGITUDES,
		"hourly": HOURLY_VARIABLES,
		"models": model,
		"timezone": ["UTC"] * 12,
		"timeformat": "unixtime",
		"wind_speed_unit": "ms",
		"start_date": str(start_date),
		"end_date": str(end_date),
		"cell_selection": "nearest",
	}
	responses = openmeteo.weather_api( url, params = params )
	if not responses:
		raise RuntimeError(f"Open-Meteo returned no previous-run forecasts for {model}.")
	clear_model_range = True
	written_rows = 0

	# Process 12 locations
	for response in responses:
		if verbose:
			print( f"\nCoordinates: {response.Latitude()}°N {response.Longitude()}°E" )
			print( f"Elevation: {response.Elevation()} m asl" )
			print( f"Timezone: {response.Timezone()}{response.TimezoneAbbreviation()}" )
			print( f"Timezone difference to GMT+0: {response.UtcOffsetSeconds()}s" )
			print( f"Model: {models[ response.Model() ]}" )

		hourly = response.Hourly()
		hourly_dataframe = hourly_dataframe_from_response( response )
		replace_forecast_rows(
			engine,
			hourly_dataframe,
			models[response.Model()],
			hourly.Time(),
			hourly.TimeEnd(),
			clear_model_range,
		)
		clear_model_range = False
		written_rows += len( hourly_dataframe )

	return written_rows


if __name__ == "__main__":
	engine = create_engine(sqlalchemy_database_url())
	openmeteo = create_openmeteo_client()

	for model in models.values():
		import_forecast_range( engine, openmeteo, model, "2024-06-01", "2026-06-01" )
