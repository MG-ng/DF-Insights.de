"""Runtime part of the Dunkelflaute forecast model: turns daily weather features into expected
wind, solar, other renewable generation, demand and the renewable share (as defined on the site:
renewable generation incl. biomass and hydro divided by grid load), plus Dunkelflaute probabilities.

Only numpy/pandas are needed here: the coefficients come from model.json, written by train.py.
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from prediction.calendar_de import calendar_features
from prediction.features import POINT_IDS

MODEL_PATH = Path( __file__ ).resolve().parent / "model.json"

OFFSHORE_POINTS = [ "off_ns", "off_bs", "ofr", "sh" ]
ONSHORE_POINTS = [ p for p in POINT_IDS if not p.startswith( "off_" ) ]
COMPONENTS = ( "wind_on", "wind_off", "pv" )


def _col( wx, point, feature ):
	return wx[ f"{point}_{feature}" ].to_numpy( dtype = float )


def design( component, wx ):
	"""Design matrix (without intercept) of one model component from daily weather features."""
	cal = calendar_features( wx.index )
	if component == "wind_on":
		cols = { f"{p}_cf": _col( wx, p, "cf" ) for p in ONSHORE_POINTS }
		cols.update( { f"{p}_ws": _col( wx, p, "ws" ) for p in ONSHORE_POINTS } )
		# icing/stable boundary layers lower winter output at the same wind speed
		cols.update( { f"{p}_ws2": _col( wx, p, "ws" ) ** 2 for p in ONSHORE_POINTS } )
		cf_mean = np.mean( [ _col( wx, p, "cf" ) for p in ONSHORE_POINTS ], axis = 0 )
		cols[ "cf_mean2" ] = cf_mean ** 2  # the fleet curve is smoother than one turbine's
		cols[ "cf_mean3" ] = cf_mean ** 3
		for harmonic in ( "cos1", "sin1", "cos2" ):  # seasonal stability, icing and wake effects
			cols[ f"cf_{harmonic}" ] = cf_mean * cal[ harmonic ].to_numpy()
	elif component == "wind_off":
		cols = { f"{p}_cf": _col( wx, p, "cf" ) for p in OFFSHORE_POINTS }
		cols.update( { f"{p}_ws": _col( wx, p, "ws" ) for p in OFFSHORE_POINTS[ :2 ] } )
		cols.update( { f"{p}_ws2": _col( wx, p, "ws" ) ** 2 for p in OFFSHORE_POINTS } )
		cols[ "cf_sin1" ] = _col( wx, "off_ns", "cf" ) * cal[ "sin1" ].to_numpy()
		cols[ "cf_cos1" ] = _col( wx, "off_ns", "cf" ) * cal[ "cos1" ].to_numpy()
	elif component == "pv":
		cols = { f"{p}_ghi": _col( wx, p, "ghi" ) for p in POINT_IDS }
		ghi_mean = np.mean( [ _col( wx, p, "ghi" ) for p in ONSHORE_POINTS ], axis = 0 )
		t_mean = np.mean( [ _col( wx, p, "t" ) for p in ONSHORE_POINTS ], axis = 0 )
		cols[ "ghi_t" ] = ghi_mean * t_mean  # module temperature losses
		cols[ "ghi_cos1" ] = ghi_mean * cal[ "cos1" ].to_numpy()  # sun angle / snow cover
		cols[ "ghi_sin1" ] = ghi_mean * cal[ "sin1" ].to_numpy()
	elif component == "load":
		t_mean = np.mean( [ _col( wx, p, "t" ) for p in ONSHORE_POINTS ], axis = 0 )
		cols = { name: cal[ name ].to_numpy() for name in cal.columns }
		cols[ "t" ] = t_mean
		cols[ "hdd" ] = np.maximum( 0.0, 15.0 - t_mean )
		cols[ "cdd" ] = np.maximum( 0.0, t_mean - 22.0 )
		cols[ "hdd_sun" ] = cols[ "hdd" ] * cols[ "sun" ]
		months = pd.to_datetime( wx.index ).month
		for month in range( 1, 13 ):
			cols[ f"m{month}" ] = ( months == month ).astype( float )
		# daylight: dark days need more lighting
		cols[ "ghi" ] = np.mean( [ _col( wx, p, "ghi" ) for p in ONSHORE_POINTS ], axis = 0 )
	else:
		raise ValueError( component )
	return pd.DataFrame( cols, index = wx.index )


def apply_linear( params, frame ):
	x = frame[ params[ "features" ] ].to_numpy( dtype = float )
	x = ( x - np.array( params[ "mean" ] ) ) / np.array( params[ "scale" ] )
	return params[ "intercept" ] + x @ np.array( params[ "coef" ] )


def capacity_at( params, dates ):
	"""Capacity index (MWh/day per unit of model output) extrapolated linearly from the training end."""
	ref = pd.Timestamp( params[ "ref_date" ] )
	days = ( pd.to_datetime( pd.Index( dates ) ) - ref ).days.to_numpy( dtype = float )
	return params[ "value" ] + params[ "slope_per_day" ] * days


def predict_components( model, wx ):
	"""Expected daily MWh of each component and the renewable share for the days in wx."""
	dates = wx.index
	out = pd.DataFrame( index = dates )
	for component in COMPONENTS + ( "load", ):
		params = model[ component ]
		unit = apply_linear( params, design( component, wx ) )
		if component != "load":
			unit = np.maximum( unit, 0.0 )
		out[ component ] = unit * capacity_at( params[ "capacity" ], dates )
	months = pd.to_datetime( dates ).month.to_numpy()
	out[ "other_re" ] = np.array( model[ "other_re" ][ "by_month" ] )[ months - 1 ]
	renewable = out[ "wind_on" ] + out[ "wind_off" ] + out[ "pv" ] + out[ "other_re" ]
	out[ "re_share" ] = renewable / out[ "load" ]
	out[ "ws_share" ] = ( out[ "wind_on" ] + out[ "wind_off" ] + out[ "pv" ] ) / out[ "load" ]
	return out


def logit( p ):
	"""Logit of a share. Shares above 0.95 (sunny, windy days with exports and curtailment) are capped:
	the thresholds of interest are far below, and the cap keeps those days from dominating error widths."""
	p = np.clip( np.asarray( p, dtype = float ), 0.01, 0.95 )
	return np.log( p / ( 1 - p ) )


def normal_cdf( z ):
	return 0.5 * ( 1.0 + np.vectorize( math.erf )( np.asarray( z ) / math.sqrt( 2.0 ) ) )


def probability_below( share, threshold, sigma ):
	"""P(true share <= threshold) given a predicted share and a Gaussian error in logit space."""
	return normal_cdf( ( logit( threshold ) - logit( share ) ) / sigma )


def load_model( path = MODEL_PATH ):
	with open( path ) as handle:
		return json.load( handle )
