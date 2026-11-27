"""Shared weather feature definitions for training (ERA5) and live forecasts (ensembles).

Everything that turns hourly weather into daily model inputs lives here, so that the backtest
and the website compute exactly the same features.
"""
import numpy as np
import pandas as pd

# Points chosen to cover where Germany's wind and PV capacity actually is:
# two offshore clusters, the windy north and east, and the PV-heavy south.
POINTS = [
	{ "id": "off_ns", "lat": 54.4, "lon": 6.5 },    # North Sea offshore wind (Borkum/Helgoland clusters)
	{ "id": "off_bs", "lat": 54.7, "lon": 13.9 },   # Baltic Sea offshore wind
	{ "id": "sh", "lat": 54.2, "lon": 9.2 },        # Schleswig-Holstein
	{ "id": "ofr", "lat": 53.4, "lon": 7.6 },       # Ostfriesland / Lower Saxony coast
	{ "id": "nds", "lat": 52.8, "lon": 9.6 },       # Lower Saxony
	{ "id": "mv", "lat": 53.7, "lon": 12.6 },       # Mecklenburg-Vorpommern
	{ "id": "bb", "lat": 52.4, "lon": 13.4 },       # Brandenburg
	{ "id": "st", "lat": 51.9, "lon": 11.6 },       # Saxony-Anhalt
	{ "id": "nrw", "lat": 51.6, "lon": 7.6 },       # North Rhine-Westphalia
	{ "id": "th", "lat": 51.0, "lon": 10.8 },       # Thuringia
	{ "id": "sn", "lat": 51.1, "lon": 13.4 },       # Saxony
	{ "id": "he", "lat": 50.5, "lon": 9.0 },        # Hesse
	{ "id": "rp", "lat": 49.7, "lon": 7.4 },        # Rhineland-Palatinate / Saarland
	{ "id": "frk", "lat": 49.6, "lon": 10.8 },      # Franconia (northern Bavaria)
	{ "id": "bw", "lat": 48.5, "lon": 9.2 },        # Baden-Württemberg
	{ "id": "by", "lat": 48.3, "lon": 12.0 },       # southern Bavaria
]
POINT_IDS = [ point[ "id" ] for point in POINTS ]

# Coarse Euro-Atlantic grid of mean sea level pressure, enough to tell the large-scale weather regimes apart
MSLP_GRID = [ ( lat, lon ) for lat in ( 35, 42, 49, 56, 63, 70 ) for lon in ( -30, -20, -10, 0, 10, 20, 30 ) ]

CUT_IN, RATED, CUT_OUT = 3.0, 11.5, 25.0


def wind_capacity_factor( speed ):
	"""Generic power curve of a modern onshore/offshore turbine at hub height (about 100 m).

	0 below cut-in, cubic rise to rated speed, 1 up to cut-out, 0 above (storm shutdown).
	Absolute level does not matter much: the model learns a scale per point, but the
	non-linearity has to be applied hourly, before averaging to days."""
	speed = np.asarray( speed, dtype = float )
	cf = ( speed ** 3 - CUT_IN ** 3 ) / ( RATED ** 3 - CUT_IN ** 3 )
	cf = np.clip( cf, 0.0, 1.0 )
	cf = np.where( speed < CUT_IN, 0.0, cf )
	cf = np.where( speed >= CUT_OUT, 0.0, cf )
	return np.where( np.isnan( speed ), np.nan, cf )


def hourly_to_daily_features( wind_100m, shortwave, temperature ):
	"""Daily features from hourly series (indexed by local time): mean wind, mean power-curve
	capacity factor, mean global radiation (W/m²) and mean temperature (°C)."""
	frame = pd.DataFrame( {
		"ws": wind_100m.astype( float ),
		"cf": wind_capacity_factor( wind_100m ),
		"ghi": shortwave.astype( float ),
		"t": temperature.astype( float ),
	} )
	day = frame.index.date
	daily = frame.groupby( day ).mean()
	enough = frame[ "ws" ].groupby( day ).count() >= 20
	daily = daily[ enough ]
	daily.index.name = "date"
	return daily
