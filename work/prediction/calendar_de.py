"""German calendar features for the electricity demand model: weekdays, nationwide public holidays
and the Christmas/New Year lull. No external dependency (the Easter date is computed)."""
import datetime as dt
from functools import lru_cache

import numpy as np
import pandas as pd


def easter_sunday( year ):
	"""Anonymous Gregorian algorithm (Meeus/Jones/Butcher)."""
	a = year % 19
	b, c = divmod( year, 100 )
	d, e = divmod( b, 4 )
	f = ( b + 8 ) // 25
	g = ( b - f + 1 ) // 3
	h = ( 19 * a + b - d - g + 15 ) % 30
	i, k = divmod( c, 4 )
	l = ( 32 + 2 * e + 2 * i - h - k ) % 7  # noqa: E741
	m = ( a + 11 * h + 22 * l ) // 451
	month, day = divmod( h + l - 7 * m + 114, 31 )
	return dt.date( year, month, day + 1 )


@lru_cache( maxsize = None )
def holidays( year ):
	"""Nationwide holidays plus the regional ones that cover a large share of the population
	(Corpus Christi, All Saints', Epiphany: Bavaria, Baden-Württemberg, NRW, ...), each with a weight
	that roughly equals the share of demand affected."""
	easter = easter_sunday( year )
	days = {
		dt.date( year, 1, 1 ): 1.0,
		easter - dt.timedelta( days = 2 ): 1.0,   # Good Friday
		easter + dt.timedelta( days = 1 ): 1.0,   # Easter Monday
		dt.date( year, 5, 1 ): 1.0,
		easter + dt.timedelta( days = 39 ): 1.0,  # Ascension
		easter + dt.timedelta( days = 50 ): 1.0,  # Whit Monday
		dt.date( year, 10, 3 ): 1.0,
		dt.date( year, 12, 25 ): 1.0,
		dt.date( year, 12, 26 ): 1.0,
		easter + dt.timedelta( days = 60 ): 0.5,  # Corpus Christi (BW, BY, HE, NW, RP, SL)
		dt.date( year, 11, 1 ): 0.5,              # All Saints' (BW, BY, NW, RP, SL)
		dt.date( year, 1, 6 ): 0.3,               # Epiphany (BW, BY, ST)
		dt.date( year, 10, 31 ): 0.2,             # Reformation Day (north and east)
	}
	return days


def calendar_features( dates ):
	"""Daily calendar design matrix for a sequence of dates."""
	dates = pd.to_datetime( pd.Index( dates ) )
	weekday = dates.weekday.values
	doy = dates.dayofyear.values
	holiday = np.array( [ holidays( d.year ).get( d.date(), 0.0 ) for d in dates ] )
	christmas = np.array( [ 1.0 if ( d.month == 12 and d.day >= 24 ) or ( d.month == 1 and d.day <= 1 ) else 0.0
							for d in dates ] )
	features = {
		"sat": ( weekday == 5 ).astype( float ),
		"sun": ( weekday == 6 ).astype( float ),
		"mon": ( weekday == 0 ).astype( float ),
		"fri": ( weekday == 4 ).astype( float ),
		"holiday": holiday,
		"christmas": christmas,
	}
	for k in ( 1, 2 ):
		features[ f"sin{k}" ] = np.sin( 2 * np.pi * k * doy / 365.25 )
		features[ f"cos{k}" ] = np.cos( 2 * np.pi * k * doy / 365.25 )
	return pd.DataFrame( features, index = dates )
