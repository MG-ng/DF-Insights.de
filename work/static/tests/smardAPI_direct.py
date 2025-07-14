"""
The API can be used to request timestamps and time series data via simple GET requests without a query string.
Results are filtered using path parameters (in curly brackets below).

Time series URL:
https://www.smard.de/app/chart_data/{FILTER}/{region}/{filterCopy}_{regionCopy}_{resolution}_{timestamp}.json
# Request returns time series data by FILTER, region and time resolution from the specified timestamp.
"""
import datetime
import json

from numpy.f2py.auxfuncs import throw_error
from requests import get
from work.Helper import FILTER, REGION_LIST
from decimal import Decimal, getcontext

# Set Decimal precision to 10 places
getcontext().prec = 10
allFilters = list(FILTER.values())

currentFilter = FILTER[ "Marktpreis: Deutschland/Luxemburg" ]
baseURL = "https://www.smard.de/app"


region = "DE"
resolution = "day"
largestNumber = 0

for region in REGION_LIST:
    for currentFilter in allFilters:
        timestampOptions = get( f"{baseURL}/chart_data/{currentFilter}/{region}/index_{resolution}.json" )
        try:
            timestampOptions = json.loads(timestampOptions.content.decode())["timestamps"]
        except Exception as e:
            if timestampOptions.status_code == 404:
                print( f"{currentFilter = } not available with {region = } and {resolution = }" )
                """
                currentFilter = 1223 not available with region = 'AT' and resolution = 'day'
                currentFilter = 1224 not available with region = 'AT' and resolution = 'day'
                currentFilter = 1225 not available with region = 'AT' and resolution = 'day'
                currentFilter = 5078 not available with region = 'AT' and resolution = 'day'
                currentFilter = 3791 not available with region = 'AT' and resolution = 'day'
                currentFilter = 1223 not available with region = 'LU' and resolution = 'day'
                currentFilter = 1224 not available with region = 'LU' and resolution = 'day'
                currentFilter = 1225 not available with region = 'LU' and resolution = 'day'
                currentFilter = 1228 not available with region = 'LU' and resolution = 'day'
                currentFilter = 4069 not available with region = 'LU' and resolution = 'day'
                currentFilter = 4070 not available with region = 'LU' and resolution = 'day'
                currentFilter = 4387 not available with region = 'LU' and resolution = 'day'
                currentFilter = 3791 not available with region = 'LU' and resolution = 'day'
                currentFilter = 5078 not available with region = 'DE-AT-LU' and resolution = 'day'
                currentFilter = 1224 not available with region = '50Hertz' and resolution = 'day'
                currentFilter = 1225 not available with region = 'Amprion' and resolution = 'day'
                currentFilter = 3791 not available with region = 'Amprion' and resolution = 'day'
                currentFilter = 1223 not available with region = 'TransnetBW' and resolution = 'day'
                currentFilter = 1225 not available with region = 'TransnetBW' and resolution = 'day'
                currentFilter = 3791 not available with region = 'TransnetBW' and resolution = 'day'
                currentFilter = 1223 not available with region = 'APG' and resolution = 'day'
                currentFilter = 1224 not available with region = 'APG' and resolution = 'day'
                currentFilter = 1225 not available with region = 'APG' and resolution = 'day'
                currentFilter = 5078 not available with region = 'APG' and resolution = 'day'
                currentFilter = 3791 not available with region = 'APG' and resolution = 'day'
                currentFilter = 1223 not available with region = 'Creos' and resolution = 'day'
                currentFilter = 1224 not available with region = 'Creos' and resolution = 'day'
                currentFilter = 1225 not available with region = 'Creos' and resolution = 'day'
                currentFilter = 1228 not available with region = 'Creos' and resolution = 'day'
                currentFilter = 4069 not available with region = 'Creos' and resolution = 'day'
                currentFilter = 4070 not available with region = 'Creos' and resolution = 'day'
                currentFilter = 4387 not available with region = 'Creos' and resolution = 'day'
                currentFilter = 3791 not available with region = 'Creos' and resolution = 'day'
                """
                continue
            print( timestampOptions.url )
            print( timestampOptions.content.decode() )
            print(e)
            print( timestampOptions )

        # Apparently, the API puts the data in buckets.
        # You cannot choose arbitrary timespans but only select these buckets of timestamps  => bucket_timestamp
        # Bucket Size depends on the resolution:
        #   - year  1 year = 1 entry in each of the 6 buckets [2019, 2020, 2021, 2022, 2023, 2024]
        #   - month 1 year = 12 month entries in each of the 8 buckets [2018, 2019, …, 2024, 2025]
        #       the 8th bucket is being filled (12 entries, but only 6 without None in the value)
        #   - week: 1 year = 52 week entries
        #       2018: up to and including calendar week 38 value = None
        #       2025: Beginning with week 26 value = None
        #   - day:  1 year = 365 day entries
        #       Starting 1.10.2018, Austria got its own grid market, before DE/AT/LU were one
        #   - hour: 1 week = 7 days => 7*24 = 168 15min entries
        #       Hour and Quarterhour include the Day Ahead market (One day in the future possible)
        #   - quarterhour: 168 * 4 = 672 entries

        # UNIX Timestamp in milliseconds
        for timestamp in timestampOptions:

            data = get( f"{baseURL}/chart_data/{currentFilter}/{region}/{currentFilter}_{region}_{resolution}_{timestamp}.json")
            data = json.loads( data.content.decode() )

            for i, tuple in enumerate( data["series"] ) :
                valueStr = str( tuple[1] )
                if valueStr == "None": continue

                if data[ "series" ][ i ][1] > largestNumber: largestNumber = tuple[1]

                parts = valueStr.split(".")
                if len( parts ) > 2 or type(tuple[1] != float):
                    throw_error("Not a Number!")
                if( len( parts ) > 1 ) :
                    aft = parts[1]
                    if( len( aft ) == 0 or len( aft ) > 2 ) :
                        print( f"{valueStr=}" )
                        print( f"{currentFilter=}")
                        print( f"{timestamp=}")
                if( len( parts ) == 1 ) :
                    print( f"{valueStr=}" )
                    print( f"{currentFilter=}" )


print(largestNumber)  # result = 2255999.0


###  Result from this data type analysis:
####    All filter values have 1 or 2 places after the decimal point

##### This is useful to adjust the database layout for performance
##### > 300000 rows will be stored in the table (5 * 24 * 365 * 7 = 306600)
##### With 37 filter rows + Timestamp + Resolution + Region + Auto_Index primary_key = 41 Columns
##### Over 306600 * 41 > 12 Mio Values!




