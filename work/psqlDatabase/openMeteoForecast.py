import openmeteo_requests

import pandas as pd
import requests_cache
from retry_requests import retry
from sqlalchemy import create_engine
from Helper import FILTER, TABLE_NAME_SMARD, DB_PARAMS, FilterTranslations

# from sklearn.metrics import root_mean_squared_error

# rms = root_mean_squared_error(y_actual, y_predicted)


# ecmwf_ifs025 doesn't deliver anything regarding wind other than on 10m height
models = {
	21: 'icon_global',
	22: 'icon_eu',
 	3: 'gfs_global',  # GFS doesn't deliver anything for wind on 180m height
}

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

if __name__ == "__main__":
	engine = create_engine('postgresql://' + DB_PARAMS["user"] + ':' + DB_PARAMS["password"] +
						   '@' + str(DB_PARAMS["host"]) + ':' + str(DB_PARAMS["port"]) + '/' + DB_PARAMS["database"])

	import openmeteo_requests

	import pandas as pd
	import requests_cache
	from retry_requests import retry

	# Set up the Open-Meteo API client with cache and retry on error
	cache_session = requests_cache.CachedSession( '.cache', expire_after = 3600 )
	retry_session = retry( cache_session, retries = 5, backoff_factor = 0.2 )
	openmeteo = openmeteo_requests.Client( session = retry_session )

	# Make sure all required weather variables are listed here
	# The order of variables in hourly or daily is important to assign them correctly below
	url = "https://previous-runs-api.open-meteo.com/v1/forecast"

	for model in models.values():
		params = {
			"latitude": [ 54, 54, 54, 52, 52, 52, 50, 50, 50, 48, 48, 48 ],
			"longitude": [ 7, 10, 13, 7, 10, 13, 7, 10, 13, 7, 10, 13 ],
			"hourly": [ "temperature_2m", "temperature_2m_previous_day1", "temperature_2m_previous_day2",
						"temperature_2m_previous_day3", "wind_speed_10m", "wind_speed_10m_previous_day1",
						"wind_speed_10m_previous_day2", "wind_speed_10m_previous_day3", "wind_direction_10m",
						"wind_direction_10m_previous_day1", "wind_direction_10m_previous_day2",
						"wind_direction_10m_previous_day3", "direct_radiation", "direct_radiation_previous_day1",
						"direct_radiation_previous_day2", "direct_radiation_previous_day3", "diffuse_radiation",
						"diffuse_radiation_previous_day1", "diffuse_radiation_previous_day2", "diffuse_radiation_previous_day3",
						"wind_speed_80m", "wind_speed_80m_previous_day1", "wind_speed_80m_previous_day2",
						"wind_speed_80m_previous_day3", "wind_speed_120m", "wind_speed_120m_previous_day1",
						"wind_speed_120m_previous_day2", "wind_speed_120m_previous_day3", "wind_speed_180m",
						"wind_speed_180m_previous_day1", "wind_speed_180m_previous_day2", "wind_speed_180m_previous_day3",
						"wind_direction_80m", "wind_direction_80m_previous_day1", "wind_direction_80m_previous_day2",
						"wind_direction_80m_previous_day3", "wind_direction_120m", "wind_direction_120m_previous_day1",
						"wind_direction_120m_previous_day2", "wind_direction_120m_previous_day3", "wind_direction_180m",
						"wind_direction_180m_previous_day1", "wind_direction_180m_previous_day2",
						"wind_direction_180m_previous_day3" ],
			"models": model,
			"timezone": [ "UTC", "UTC", "UTC", "UTC", "UTC", "UTC", "UTC", "UTC", "UTC", "UTC", "UTC", "UTC" ],
			"timeformat": "unixtime",
			"wind_speed_unit": "ms",
			"start_date": "2024-04-01",
			"end_date": "2025-09-01",
			"cell_selection": "nearest",
		}
		responses = openmeteo.weather_api( url, params = params )

		# Process 12 locations and 4 models
		for response in responses:
			print( f"\nCoordinates: {response.Latitude()}°N {response.Longitude()}°E" )
			print( f"Elevation: {response.Elevation()} m asl" )
			print( f"Timezone: {response.Timezone()}{response.TimezoneAbbreviation()}" )
			print( f"Timezone difference to GMT+0: {response.UtcOffsetSeconds()}s" )
			print( f"Model: {models[ response.Model() ]}" )

			# Process hourly data. The order of variables needs to be the same as requested.
			hourly = response.Hourly()
			hourly_temperature_2m = hourly.Variables( 0 ).ValuesAsNumpy()
			hourly_temperature_2m_previous_day1 = hourly.Variables( 1 ).ValuesAsNumpy()
			hourly_temperature_2m_previous_day2 = hourly.Variables( 2 ).ValuesAsNumpy()
			hourly_temperature_2m_previous_day3 = hourly.Variables( 3 ).ValuesAsNumpy()
			hourly_wind_speed_10m = hourly.Variables( 4 ).ValuesAsNumpy()
			hourly_wind_speed_10m_previous_day1 = hourly.Variables( 5 ).ValuesAsNumpy()
			hourly_wind_speed_10m_previous_day2 = hourly.Variables( 6 ).ValuesAsNumpy()
			hourly_wind_speed_10m_previous_day3 = hourly.Variables( 7 ).ValuesAsNumpy()
			hourly_wind_direction_10m = hourly.Variables( 8 ).ValuesAsNumpy()
			hourly_wind_direction_10m_previous_day1 = hourly.Variables( 9 ).ValuesAsNumpy()
			hourly_wind_direction_10m_previous_day2 = hourly.Variables( 10 ).ValuesAsNumpy()
			hourly_wind_direction_10m_previous_day3 = hourly.Variables( 11 ).ValuesAsNumpy()
			hourly_direct_radiation = hourly.Variables( 12 ).ValuesAsNumpy()
			hourly_direct_radiation_previous_day1 = hourly.Variables( 13 ).ValuesAsNumpy()
			hourly_direct_radiation_previous_day2 = hourly.Variables( 14 ).ValuesAsNumpy()
			hourly_direct_radiation_previous_day3 = hourly.Variables( 15 ).ValuesAsNumpy()
			hourly_diffuse_radiation = hourly.Variables( 16 ).ValuesAsNumpy()
			hourly_diffuse_radiation_previous_day1 = hourly.Variables( 17 ).ValuesAsNumpy()
			hourly_diffuse_radiation_previous_day2 = hourly.Variables( 18 ).ValuesAsNumpy()
			hourly_diffuse_radiation_previous_day3 = hourly.Variables( 19 ).ValuesAsNumpy()
			hourly_wind_speed_80m = hourly.Variables( 20 ).ValuesAsNumpy()
			hourly_wind_speed_80m_previous_day1 = hourly.Variables( 21 ).ValuesAsNumpy()
			hourly_wind_speed_80m_previous_day2 = hourly.Variables( 22 ).ValuesAsNumpy()
			hourly_wind_speed_80m_previous_day3 = hourly.Variables( 23 ).ValuesAsNumpy()
			hourly_wind_speed_120m = hourly.Variables( 24 ).ValuesAsNumpy()
			hourly_wind_speed_120m_previous_day1 = hourly.Variables( 25 ).ValuesAsNumpy()
			hourly_wind_speed_120m_previous_day2 = hourly.Variables( 26 ).ValuesAsNumpy()
			hourly_wind_speed_120m_previous_day3 = hourly.Variables( 27 ).ValuesAsNumpy()
			hourly_wind_speed_180m = hourly.Variables( 28 ).ValuesAsNumpy()
			hourly_wind_speed_180m_previous_day1 = hourly.Variables( 29 ).ValuesAsNumpy()
			hourly_wind_speed_180m_previous_day2 = hourly.Variables( 30 ).ValuesAsNumpy()
			hourly_wind_speed_180m_previous_day3 = hourly.Variables( 31 ).ValuesAsNumpy()
			hourly_wind_direction_80m = hourly.Variables( 32 ).ValuesAsNumpy()
			hourly_wind_direction_80m_previous_day1 = hourly.Variables( 33 ).ValuesAsNumpy()
			hourly_wind_direction_80m_previous_day2 = hourly.Variables( 34 ).ValuesAsNumpy()
			hourly_wind_direction_80m_previous_day3 = hourly.Variables( 35 ).ValuesAsNumpy()
			hourly_wind_direction_120m = hourly.Variables( 36 ).ValuesAsNumpy()
			hourly_wind_direction_120m_previous_day1 = hourly.Variables( 37 ).ValuesAsNumpy()
			hourly_wind_direction_120m_previous_day2 = hourly.Variables( 38 ).ValuesAsNumpy()
			hourly_wind_direction_120m_previous_day3 = hourly.Variables( 39 ).ValuesAsNumpy()
			hourly_wind_direction_180m = hourly.Variables( 40 ).ValuesAsNumpy()
			hourly_wind_direction_180m_previous_day1 = hourly.Variables( 41 ).ValuesAsNumpy()
			hourly_wind_direction_180m_previous_day2 = hourly.Variables( 42 ).ValuesAsNumpy()
			hourly_wind_direction_180m_previous_day3 = hourly.Variables( 43 ).ValuesAsNumpy()


			hourly_data = { # to not confuse with dates with correct time zone
				# "date": pd.date_range(
				# 	start = pd.to_datetime( hourly.Time(), unit = "s", utc = True ),
				# 	end = pd.to_datetime( hourly.TimeEnd(), unit = "s", utc = True ),
				# 	freq = pd.Timedelta( seconds = hourly.Interval() ),
				# 	inclusive = "left" ),
				"timestamp_s": range(hourly.Time(), hourly.TimeEnd(), hourly.Interval())
			}


			hourly_data["lat"] = response.Latitude()
			hourly_data["lng"] = response.Longitude()
			hourly_data["elevation"] = response.Elevation()
			hourly_data["model"] = models[ response.Model() ]
			hourly_data["temporal_resolution"] = "hour"

			hourly_data[ "temperature_2m" ] = hourly_temperature_2m
			hourly_data[ "temperature_2m_previous_day1" ] = hourly_temperature_2m_previous_day1
			hourly_data[ "temperature_2m_previous_day2" ] = hourly_temperature_2m_previous_day2
			hourly_data[ "temperature_2m_previous_day3" ] = hourly_temperature_2m_previous_day3
			hourly_data[ "wind_speed_10m" ] = hourly_wind_speed_10m
			hourly_data[ "wind_speed_10m_previous_day1" ] = hourly_wind_speed_10m_previous_day1
			hourly_data[ "wind_speed_10m_previous_day2" ] = hourly_wind_speed_10m_previous_day2
			hourly_data[ "wind_speed_10m_previous_day3" ] = hourly_wind_speed_10m_previous_day3
			hourly_data[ "wind_direction_10m" ] = hourly_wind_direction_10m
			hourly_data[ "wind_direction_10m_previous_day1" ] = hourly_wind_direction_10m_previous_day1
			hourly_data[ "wind_direction_10m_previous_day2" ] = hourly_wind_direction_10m_previous_day2
			hourly_data[ "wind_direction_10m_previous_day3" ] = hourly_wind_direction_10m_previous_day3
			hourly_data[ "direct_radiation" ] = hourly_direct_radiation
			hourly_data[ "direct_radiation_previous_day1" ] = hourly_direct_radiation_previous_day1
			hourly_data[ "direct_radiation_previous_day2" ] = hourly_direct_radiation_previous_day2
			hourly_data[ "direct_radiation_previous_day3" ] = hourly_direct_radiation_previous_day3
			hourly_data[ "diffuse_radiation" ] = hourly_diffuse_radiation
			hourly_data[ "diffuse_radiation_previous_day1" ] = hourly_diffuse_radiation_previous_day1
			hourly_data[ "diffuse_radiation_previous_day2" ] = hourly_diffuse_radiation_previous_day2
			hourly_data[ "diffuse_radiation_previous_day3" ] = hourly_diffuse_radiation_previous_day3
			hourly_data[ "wind_speed_80m" ] = hourly_wind_speed_80m
			hourly_data[ "wind_speed_80m_previous_day1" ] = hourly_wind_speed_80m_previous_day1
			hourly_data[ "wind_speed_80m_previous_day2" ] = hourly_wind_speed_80m_previous_day2
			hourly_data[ "wind_speed_80m_previous_day3" ] = hourly_wind_speed_80m_previous_day3
			hourly_data[ "wind_speed_120m" ] = hourly_wind_speed_120m
			hourly_data[ "wind_speed_120m_previous_day1" ] = hourly_wind_speed_120m_previous_day1
			hourly_data[ "wind_speed_120m_previous_day2" ] = hourly_wind_speed_120m_previous_day2
			hourly_data[ "wind_speed_120m_previous_day3" ] = hourly_wind_speed_120m_previous_day3
			hourly_data[ "wind_speed_180m" ] = hourly_wind_speed_180m
			hourly_data[ "wind_speed_180m_previous_day1" ] = hourly_wind_speed_180m_previous_day1
			hourly_data[ "wind_speed_180m_previous_day2" ] = hourly_wind_speed_180m_previous_day2
			hourly_data[ "wind_speed_180m_previous_day3" ] = hourly_wind_speed_180m_previous_day3
			hourly_data[ "wind_direction_80m" ] = hourly_wind_direction_80m
			hourly_data[ "wind_direction_80m_previous_day1" ] = hourly_wind_direction_80m_previous_day1
			hourly_data[ "wind_direction_80m_previous_day2" ] = hourly_wind_direction_80m_previous_day2
			hourly_data[ "wind_direction_80m_previous_day3" ] = hourly_wind_direction_80m_previous_day3
			hourly_data[ "wind_direction_120m" ] = hourly_wind_direction_120m
			hourly_data[ "wind_direction_120m_previous_day1" ] = hourly_wind_direction_120m_previous_day1
			hourly_data[ "wind_direction_120m_previous_day2" ] = hourly_wind_direction_120m_previous_day2
			hourly_data[ "wind_direction_120m_previous_day3" ] = hourly_wind_direction_120m_previous_day3
			hourly_data[ "wind_direction_180m" ] = hourly_wind_direction_180m
			hourly_data[ "wind_direction_180m_previous_day1" ] = hourly_wind_direction_180m_previous_day1
			hourly_data[ "wind_direction_180m_previous_day2" ] = hourly_wind_direction_180m_previous_day2
			hourly_data[ "wind_direction_180m_previous_day3" ] = hourly_wind_direction_180m_previous_day3

			hourly_dataframe = pd.DataFrame( data = hourly_data )
			# print( "\nHourly data\n", hourly_dataframe )

			hourly_dataframe.set_index( [ 'model', 'timestamp_s', 'lat', 'lng', 'temporal_resolution' ] )

			hourly_dataframe.to_sql( 'weather_forecasts_data_raw', engine, if_exists = 'append' )


