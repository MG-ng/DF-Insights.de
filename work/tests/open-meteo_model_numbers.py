
import openmeteo_requests

import pandas as pd
import requests_cache
from retry_requests import retry

from config import REQUEST_CACHE_DIR
from psqlDatabase.openMeteoForecastInsertion import models

# Set up the Open-Meteo API client with cache and retry on error
REQUEST_CACHE_DIR.mkdir(parents = True, exist_ok = True)
cache_session = requests_cache.CachedSession(
	str(REQUEST_CACHE_DIR / 'openmeteo_model_numbers'),
	expire_after = 3600
)
retry_session = retry( cache_session, retries = 5, backoff_factor = 0.2 )
openmeteo = openmeteo_requests.Client( session = retry_session )

# Make sure all required weather variables are listed here
# The order of variables in hourly or daily is important to assign them correctly below
url = "https://previous-runs-api.open-meteo.com/v1/forecast"

for model in models.values():
	params = {
		"latitude": [ 54 ],
		"longitude": [ 7 ],
		"hourly": [ "temperature_2m_previous_day1" ],
		"models": model,
		"timezone": [ "UTC" ],
		"timeformat": "unixtime",
		"wind_speed_unit": "ms",
		"start_date": "2024-04-01",
		"end_date": "2024-04-07",
		"cell_selection": "nearest"
	}
	responses = openmeteo.weather_api( url, params = params )

	# Process 12 locations and 4 models
	for response in responses:
		print( f"Model Nº: {response.Model()} = {model}" )
