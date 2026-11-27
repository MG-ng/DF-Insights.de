import openmeteo_requests
import pandas as pd
from retry_requests import retry
from sqlalchemy import TIMESTAMP, create_engine, inspect, text

from config import create_cached_http_session, sqlalchemy_database_url
from Helper import TABLE_NAME_OPEN_METEO


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


# The order of these variables is the order of hourly.Variables(i) in the response
HOURLY_VARIABLES = [ "temperature_2m", "wind_speed_10m", "wind_speed_100m", "wind_direction_10m",
					 "wind_direction_100m", "direct_radiation", "diffuse_radiation" ]
LATITUDES = [ 54, 54, 54, 52, 52, 52, 50, 50, 50, 48, 48, 48 ]
LONGITUDES = [ 7, 10, 13, 7, 10, 13, 7, 10, 13, 7, 10, 13 ]
url = "https://archive-api.open-meteo.com/v1/archive"


def create_engine_from_config():
	return create_engine(sqlalchemy_database_url())


def create_openmeteo_client(cache_name="openmeteo_archive", expire_after=-1):
	"""Open-Meteo API client with cache and retry on error.

	The full import caches forever (old archive data does not change). The
	incremental update passes a short expiry, so recent days are fetched again.
	"""
	cache_session = create_cached_http_session(cache_name, expire_after=expire_after)
	retry_session = retry( cache_session, retries = 5, backoff_factor = 0.2 )
	return openmeteo_requests.Client( session = retry_session )


def replace_historical_rows(engine, dataframe, start_date, end_date, clear_date_range):
	with engine.begin() as connection:
		if clear_date_range and inspect(connection).has_table(TABLE_NAME_OPEN_METEO):
			connection.execute(
				text(f"""
					DELETE FROM {TABLE_NAME_OPEN_METEO}
					WHERE date >= :start_date
					  AND date < :end_date;
				"""),  # nosec B608 # table name is a Helper.py constant, values are bound parameters
				{
					"start_date": start_date,
					"end_date": end_date,
				},
			)
		# Store real instants (timestamptz) so they can be compared with the UTC SMARD timestamps directly
		dataframe.to_sql(TABLE_NAME_OPEN_METEO, connection, if_exists="append", index=False,
						 dtype={"date": TIMESTAMP(timezone=True)})


def hourly_dataframe_from_response(response):
	""" Model gets selected automatically (Best Match) and I therefore don't know which row of these is applicable
	Data Set	Region		Spatial Resolution	Temporal Res	Data Availability	Update frequency
	ECMWF IFS		Global	9 km				Hourly			2017 to present	Daily with 2 days delay
	ERA5			Global	0.25° (~25 km)		Hourly			1940 to present	Daily with 5 days delay
	ERA5-Land		Global	0.1° (~11 km)		Hourly			1950 to present	Daily with 5 days delay
	ERA5-Ensemble	Global	0.5° (~55 km)		3-Hourly		1940 to present	Daily with 5 days delay
	CERRA			Europe	5 km				Hourly			1985 to June 2021	-
	ECMWF IFS Assimilation Long-Window	Global	9 km	6-Hourly	2024 to present	Daily with 2 days delay
	"""
	hourly = response.Hourly()
	hourly_data = { "date": pd.date_range(
		start = pd.to_datetime( hourly.Time(), unit = "s", utc = True ),
		end = pd.to_datetime( hourly.TimeEnd(), unit = "s", utc = True ),
		freq = pd.Timedelta( seconds = hourly.Interval() ),
		inclusive = "left",
	) }

	hourly_data[ "unix_timestamp_s" ] = range( hourly.Time(), hourly.TimeEnd(), hourly.Interval() )
	hourly_data[ "lat" ] = response.Latitude()
	hourly_data[ "lng" ] = response.Longitude()
	hourly_data[ "temporal_resolution" ] = 'hour'
	hourly_data[ "elevation" ] = response.Elevation()
	hourly_data[ "model" ] = response.Model()
	for index, variable in enumerate( HOURLY_VARIABLES ):
		hourly_data[ variable ] = hourly.Variables( index ).ValuesAsNumpy()

	return pd.DataFrame( data = hourly_data )


def import_historical_range(engine, openmeteo, start_date, end_date, verbose=True):
	"""Fetch [start_date, end_date] (inclusive dates, UTC) for all 12 locations and replace that range in the table.

	Returns the number of rows written.
	"""
	params = {
		"latitude": LATITUDES,
		"longitude": LONGITUDES,
		"start_date": str(start_date),
		"end_date": str(end_date),
		"hourly": HOURLY_VARIABLES,
		"timezone": [ "UTC" ] * 12,  # SMARD timestamps are UTC as well; local time is only applied for display
		"wind_speed_unit": "ms",
	}
	responses = openmeteo.weather_api( url, params = params )
	if not responses:
		raise RuntimeError(f"Open-Meteo returned no historical data for {start_date} to {end_date}.")
	clear_date_range = True
	written_rows = 0

	# Process 12 locations
	for response in responses:
		if verbose:
			print( f"\nCoordinates: {response.Latitude()}°N {response.Longitude()}°E" )
			print( f"Elevation: {response.Elevation()} m asl" )
			print( f"Timezone: {response.Timezone()}{response.TimezoneAbbreviation()}" )
			print( f"Timezone difference to GMT+0: {response.UtcOffsetSeconds()}s" )

		hourly = response.Hourly()
		hourly_dataframe = hourly_dataframe_from_response( response )
		if verbose:
			pd.set_option( 'display.max_columns', None )
			print( "\nHourly data\n", hourly_dataframe )

		replace_historical_rows(
			engine,
			hourly_dataframe,
			hourly_dataframe["date"].iloc[0].to_pydatetime(),
			pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True).to_pydatetime(),
			clear_date_range,
		)
		clear_date_range = False
		written_rows += len( hourly_dataframe )

	return written_rows


if __name__ == '__main__':
	engine = create_engine_from_config()
	openmeteo = create_openmeteo_client()

	for year in [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]:
		import_historical_range(
			engine,
			openmeteo,
			str(year) + "-01-01",
			str(year) + "-12-31" if year!=2026 else (str(year) + "-06-01"),  # More Weather than SMARD data needed
		)
