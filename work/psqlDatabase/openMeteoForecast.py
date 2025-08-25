import openmeteo_requests

import pandas as pd
import requests_cache
from retry_requests import retry

# Setup the Open-Meteo API client with cache and retry on error
cache_session = requests_cache.CachedSession('.cache', expire_after = 3600)
retry_session = retry(cache_session, retries = 5, backoff_factor = 0.2)
openmeteo = openmeteo_requests.Client(session = retry_session)

# Make sure all required weather variables are listed here
# The order of variables in hourly or daily is important to assign them correctly below
url = "https://api.open-meteo.com/v1/forecast"
params = {
	"latitude": 53,
	"longitude": 10,
	"hourly": ["wind_speed_80m", "wind_speed_120m", "direct_radiation", "diffuse_radiation", "wind_direction_120m",
			   "wind_speed_10m", "wind_direction_10m", "temperature_2m", "wind_speed_180m",
			   "wind_direction_180m", "wind_direction_80m"],
	"timezone": "Europe/Berlin",
	"forecast_days": 16,
}
responses = openmeteo.weather_api(url, params=params)

# Process first location. Add a for-loop for multiple locations or weather models
response = responses[0]
print(f"Coordinates: {response.Latitude()}°N {response.Longitude()}°E")
print(f"Elevation: {response.Elevation()} m asl")
print(f"Timezone: {response.Timezone()}{response.TimezoneAbbreviation()}")
print(f"Timezone difference to GMT+0: {response.UtcOffsetSeconds()}s")

# Process hourly data. The order of variables needs to be the same as requested.
hourly = response.Hourly()
hourly_wind_speed_80m = hourly.Variables(0).ValuesAsNumpy()
hourly_wind_speed_120m = hourly.Variables(1).ValuesAsNumpy()
hourly_direct_radiation = hourly.Variables(2).ValuesAsNumpy()
hourly_diffuse_radiation = hourly.Variables(3).ValuesAsNumpy()
hourly_wind_direction_120m = hourly.Variables(4).ValuesAsNumpy()
hourly_wind_speed_10m = hourly.Variables(5).ValuesAsNumpy()
hourly_wind_direction_10m = hourly.Variables(6).ValuesAsNumpy()
hourly_temperature_2m = hourly.Variables(7).ValuesAsNumpy()
hourly_wind_speed_180m = hourly.Variables(8).ValuesAsNumpy()
hourly_wind_direction_180m = hourly.Variables(9).ValuesAsNumpy()
hourly_wind_direction_80m = hourly.Variables(10).ValuesAsNumpy()

hourly_data = {"date": pd.date_range(
	start = pd.to_datetime(hourly.Time(), unit = "s", utc = True),
	end = pd.to_datetime(hourly.TimeEnd(), unit = "s", utc = True),
	freq = pd.Timedelta(seconds = hourly.Interval()),
	inclusive = "left",
	tz = "Europe/Berlin"
)}

hourly_data["wind_speed_80m"] = hourly_wind_speed_80m
hourly_data["wind_speed_120m"] = hourly_wind_speed_120m
hourly_data["direct_radiation"] = hourly_direct_radiation
hourly_data["diffuse_radiation"] = hourly_diffuse_radiation
hourly_data["wind_direction_120m"] = hourly_wind_direction_120m
hourly_data["wind_speed_10m"] = hourly_wind_speed_10m
hourly_data["wind_direction_10m"] = hourly_wind_direction_10m
hourly_data["temperature_2m"] = hourly_temperature_2m
hourly_data["wind_speed_180m"] = hourly_wind_speed_180m
hourly_data["wind_direction_180m"] = hourly_wind_direction_180m
hourly_data["wind_direction_80m"] = hourly_wind_direction_80m

pd.set_option('display.max_columns', None)
hourly_dataframe = pd.DataFrame(data = hourly_data)
print("\nHourly data\n", hourly_dataframe)



