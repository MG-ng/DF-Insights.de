import json, pytz
from requests import get
from datetime import datetime

def convert_unix_timestamp(timestamp, is_milliseconds=True):
    if is_milliseconds:
        timestamp = timestamp / 1000.0  # Convert milliseconds to seconds
    dt_object = datetime.fromtimestamp(timestamp, pytz.timezone("Europe/Berlin"))
    return dt_object.strftime('%Y-%m-%d %H:%M:%S')

FLAG = -1e8
baseURL = "https://www.smard.de/app"
priceFilterDict = {
    4169: "Marktpreis: Deutschland/Luxemburg",
    5078: "Marktpreis: Anrainer DE/LU",
    4170: "Marktpreis: Österreich"
}
priceFilter = list( priceFilterDict.keys() )
print(priceFilter, priceFilterDict)
bucketList = {}
timestampBuckets = []

# First get the rows with the Timestamp Buckets
timestampedRows: list = []
for resolution in ["day"]:
    for region in ["DE-AT-LU", "DE-LU", "AT"]:  # REGION_LIST:
        for filterIndex, currentFilter in enumerate( priceFilter ):
            response = get( f"{baseURL}/chart_data/{currentFilter}/{region}/index_{resolution}.json" )
            try:
                print( response.url, response.status_code )
                timestampBuckets = json.loads(response.content.decode())[ "timestamps" ]
            except Exception as e:
                if response.status_code == 404:
                    continue
                print( e )

            for timestamp in timestampBuckets:
                timestampedRows.append( (timestamp, True, region, resolution, *[None] * filterIndex, FLAG, *[None] * (
                            len( priceFilter ) -filterIndex-1) ) )
                response = get( f"{baseURL}/chart_data/{currentFilter}/{region}/{currentFilter}_{region}_{resolution}_{timestamp}.json" )
                data = json.loads( response.content.decode() )

                for tuple in data["series"]:
                    # print(data)  # {…, 'series': [[1420066800000, 12508.5], [1420153200000, None]] }
                    if tuple[1] != None:
                        timestampedRows.append( (tuple[ 0 ], False, region, resolution,
                             *[None] * filterIndex, tuple[1], *[None] * (len(priceFilter)-filterIndex-1) ) )

            bucketList[ str(currentFilter) +"-"+ region +"-"+ resolution ] = timestampedRows
            timestampedRows = []

print("Result:")

for key in bucketList:
    print( key, " - " + priceFilterDict[ int(key.split("-")[0]) ] )
    timestampedRows = bucketList[ key ]
    timestampedRows.sort( key = lambda row: row[ 0 ] )
    for i in range( 3 ):  # print earliest x datapoints in the API
        print( convert_unix_timestamp(timestampedRows[i][0]), timestampedRows[i] )



# Shows that the earliest data points for Germany and Austria are on the 2018/10/01
# On that day, Austria got its own price zone

"""
[4169, 5078, 4170] {4169: 'Marktpreis: Deutschland/Luxemburg', 5078: 'Marktpreis: Anrainer DE/LU', 4170: 'Marktpreis: Österreich'}
https://www.smard.de/app/chart_data/4169/DE-AT-LU/index_day.json 200
https://www.smard.de/app/chart_data/5078/DE-AT-LU/index_day.json 404
https://www.smard.de/app/chart_data/4170/DE-AT-LU/index_day.json 200
https://www.smard.de/app/chart_data/4169/DE-LU/index_day.json 200
https://www.smard.de/app/chart_data/5078/DE-LU/index_day.json 200
https://www.smard.de/app/chart_data/4170/DE-LU/index_day.json 200
https://www.smard.de/app/chart_data/4169/AT/index_day.json 200
https://www.smard.de/app/chart_data/5078/AT/index_day.json 404
https://www.smard.de/app/chart_data/4170/AT/index_day.json 200
Result:
4169-DE-AT-LU-day  - Marktpreis: Deutschland/Luxemburg
2018-01-01 00:00:00 (1514761200000, True, 'DE-AT-LU', 'day', -100000000.0, None, None)
2018-10-01 00:00:00 (1538344800000, False, 'DE-AT-LU', 'day', 61.24, None, None)
2018-10-02 00:00:00 (1538431200000, False, 'DE-AT-LU', 'day', 42.34, None, None)
4170-DE-AT-LU-day  - Marktpreis: Österreich
2018-01-01 00:00:00 (1514761200000, True, 'DE-AT-LU', 'day', None, None, -100000000.0)
2018-10-01 00:00:00 (1538344800000, False, 'DE-AT-LU', 'day', None, None, 63.19)
2018-10-02 00:00:00 (1538431200000, False, 'DE-AT-LU', 'day', None, None, 49.75)
4169-DE-LU-day  - Marktpreis: Deutschland/Luxemburg
2018-01-01 00:00:00 (1514761200000, True, 'DE-LU', 'day', -100000000.0, None, None)
2018-10-01 00:00:00 (1538344800000, False, 'DE-LU', 'day', 61.24, None, None)
2018-10-02 00:00:00 (1538431200000, False, 'DE-LU', 'day', 42.34, None, None)
5078-DE-LU-day  - Marktpreis: Anrainer DE/LU
2019-01-01 00:00:00 (1546297200000, True, 'DE-LU', 'day', None, -100000000.0, None)
2019-11-20 00:00:00 (1574204400000, False, 'DE-LU', 'day', None, 54.03, None)
2019-11-21 00:00:00 (1574290800000, False, 'DE-LU', 'day', None, 49.23, None)
4170-DE-LU-day  - Marktpreis: Österreich
2018-01-01 00:00:00 (1514761200000, True, 'DE-LU', 'day', None, None, -100000000.0)
2018-10-01 00:00:00 (1538344800000, False, 'DE-LU', 'day', None, None, 63.19)
2018-10-02 00:00:00 (1538431200000, False, 'DE-LU', 'day', None, None, 49.75)
4169-AT-day  - Marktpreis: Deutschland/Luxemburg
2018-01-01 00:00:00 (1514761200000, True, 'AT', 'day', -100000000.0, None, None)
2018-10-01 00:00:00 (1538344800000, False, 'AT', 'day', 61.24, None, None)
2018-10-02 00:00:00 (1538431200000, False, 'AT', 'day', 42.34, None, None)
4170-AT-day  - Marktpreis: Österreich
2018-01-01 00:00:00 (1514761200000, True, 'AT', 'day', None, None, -100000000.0)
2018-10-01 00:00:00 (1538344800000, False, 'AT', 'day', None, None, 63.19)
2018-10-02 00:00:00 (1538431200000, False, 'AT', 'day', None, None, 49.75)
"""

