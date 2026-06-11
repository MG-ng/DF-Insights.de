import openmeteo_requests
import pandas as pd
import requests_cache
from retry_requests import retry
from sqlalchemy import create_engine, inspect, text

from config import REQUEST_CACHE_DIR, sqlalchemy_database_url
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


engine = create_engine(sqlalchemy_database_url())


# Set up the Open-Meteo API client with cache and retry on error
REQUEST_CACHE_DIR.mkdir(parents = True, exist_ok = True)
cache_session = requests_cache.CachedSession( str(REQUEST_CACHE_DIR / 'openmeteo_archive'), expire_after = -1 )
retry_session = retry( cache_session, retries = 5, backoff_factor = 0.2 )
openmeteo = openmeteo_requests.Client( session = retry_session )

# Make sure all required weather variables are listed here
# The order of variables in hourly or daily is important to assign them correctly below
url = "https://archive-api.open-meteo.com/v1/archive"


def replace_historical_rows(dataframe, start_date, end_date, clear_date_range):
	with engine.begin() as connection:
		if clear_date_range and inspect(connection).has_table(TABLE_NAME_OPEN_METEO):
			connection.execute(
				text(f"""
					DELETE FROM {TABLE_NAME_OPEN_METEO}
					WHERE date >= :start_date
					  AND date < :end_date;
				"""),
				{
					"start_date": start_date,
					"end_date": end_date,
				},
			)
		dataframe.to_sql(TABLE_NAME_OPEN_METEO, connection, if_exists="append", index=False)


if __name__ == '__main__':

	for year in [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]:
		params = {
			"latitude": [ 54, 54, 54, 52, 52, 52, 50, 50, 50, 48, 48, 48 ],
			"longitude": [ 7, 10, 13, 7, 10, 13, 7, 10, 13, 7, 10, 13 ],
			"start_date": 	str(year) + "-01-01",
			"end_date": 	str(year) + "-12-31" if year!=2026 else (str(year) + "-06-01"),  # More Weather than SMARD data needed
			"hourly": [ "temperature_2m", "wind_speed_10m", "wind_speed_100m", "wind_direction_10m", "wind_direction_100m",
						"direct_radiation", "diffuse_radiation" ],
			"timezone": [ "Europe/Berlin", "Europe/Berlin", "Europe/Berlin", "Europe/Berlin", "Europe/Berlin", "Europe/Berlin",
						  "Europe/Berlin", "Europe/Berlin", "Europe/Berlin", "Europe/Berlin", "Europe/Berlin",
						  "Europe/Berlin" ],  # TODO: Remove for easier SMARD join
			"wind_speed_unit": "ms",
		}
		responses = openmeteo.weather_api( url, params = params )
		if not responses:
			raise RuntimeError(f"Open-Meteo returned no historical data for {year}.")
		clear_date_range = True

		# Process 12 locations
		for response in responses:
			print(response)
			print( f"\nCoordinates: {response.Latitude()}°N {response.Longitude()}°E" )
			print( f"Elevation: {response.Elevation()} m asl" )
			print( f"Timezone: {response.Timezone()}{response.TimezoneAbbreviation()}" )
			print( f"Timezone difference to GMT+0: {response.UtcOffsetSeconds()}s" )

			# Process hourly data. The order of variables needs to be the same as requested.
			hourly = response.Hourly()
			hourly_lat = response.Latitude()
			hourly_lng = response.Longitude()
			hourly_temperature_2m = hourly.Variables( 0 ).ValuesAsNumpy()
			hourly_wind_speed_10m = hourly.Variables( 1 ).ValuesAsNumpy()
			hourly_wind_speed_100m = hourly.Variables( 2 ).ValuesAsNumpy()
			hourly_wind_direction_10m = hourly.Variables( 3 ).ValuesAsNumpy()
			hourly_wind_direction_100m = hourly.Variables( 4 ).ValuesAsNumpy()
			hourly_direct_radiation = hourly.Variables( 5 ).ValuesAsNumpy()
			hourly_diffuse_radiation = hourly.Variables( 6 ).ValuesAsNumpy()

			hourly_data = { "date": pd.date_range(
				# TODO: change timezone to utc in the request too
				start = pd.to_datetime( hourly.Time(), unit = "s", utc = True ),
				end = pd.to_datetime( hourly.TimeEnd(), unit = "s", utc = True ),
				freq = pd.Timedelta( seconds = hourly.Interval() ),
				inclusive = "left",
			).tz_convert("Europe/Berlin") }

			hourly_data[ "unix_timestamp_s" ] = hourly.Time()
			hourly_data[ "lat" ] = hourly_lat
			hourly_data[ "lng" ] = hourly_lng
			hourly_data[ "temporal_resolution" ] = 'hour'
			hourly_data[ "elevation" ] = response.Elevation()
			hourly_data[ "model" ] = response.Model()
			""" Model gets selected automatically (Best Match) and I therefore don't know which row of these is applicable
			Data Set	Region		Spatial Resolution	Temporal Res	Data Availability	Update frequency
			ECMWF IFS		Global	9 km				Hourly			2017 to present	Daily with 2 days delay
			ERA5			Global	0.25° (~25 km)		Hourly			1940 to present	Daily with 5 days delay
			ERA5-Land		Global	0.1° (~11 km)		Hourly			1950 to present	Daily with 5 days delay
			ERA5-Ensemble	Global	0.5° (~55 km)		3-Hourly		1940 to present	Daily with 5 days delay
			CERRA			Europe	5 km				Hourly			1985 to June 2021	-
			ECMWF IFS Assimilation Long-Window	Global	9 km	6-Hourly	2024 to present	Daily with 2 days delay
			"""

			hourly_data[ "temperature_2m" ] = hourly_temperature_2m
			hourly_data[ "wind_speed_10m" ] = hourly_wind_speed_10m
			hourly_data[ "wind_speed_100m" ] = hourly_wind_speed_100m
			hourly_data[ "wind_direction_10m" ] = hourly_wind_direction_10m
			hourly_data[ "wind_direction_100m" ] = hourly_wind_direction_100m
			hourly_data[ "direct_radiation" ] = hourly_direct_radiation
			hourly_data[ "diffuse_radiation" ] = hourly_diffuse_radiation


			pd.set_option( 'display.max_columns', None )
			hourly_dataframe = pd.DataFrame( data = hourly_data )
			print( "\nHourly data\n", hourly_dataframe )

			replace_historical_rows(
				hourly_dataframe,
				hourly_dataframe["date"].iloc[0].to_pydatetime(),
				pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True)
					.tz_convert("Europe/Berlin")
					.to_pydatetime(),
				clear_date_range,
			)
			clear_date_range = False
