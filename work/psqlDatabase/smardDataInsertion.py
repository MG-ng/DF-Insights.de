import json
from decimal import getcontext

from requests import get

from config import DB_PARAMS
from Helper import FILTER, TABLE_NAME_SMARD, FLAG, Resolution, \
	FilterTranslationsList
from QuerySimple import get_timestamp_buckets
from databaseSetup import insert_optional_data_in_batches

allFilters = list(FILTER.values())
getcontext().prec = 10
baseURL = "https://www.smard.de/app"


#######################################################
##### ATTENTION: THIS SCRIPT TAKES MULTIPLE HOURS #####
#######################################################

# First insert the rows with the Timestamps
timestampedRows = []
for resolutionEnum in Resolution:
    resolution = resolutionEnum.value
    for region in ["DE"]:  # REGION_LIST:
        for filterIndex, currentFilter in enumerate( allFilters ):
            timestampBuckets = get( f"{baseURL}/chart_data/{currentFilter}/{region}/index_{resolution}.json" )
            try:
                timestampBuckets = json.loads(timestampBuckets.content.decode())["timestamps"]
            except Exception as e:
                if timestampBuckets.status_code == 404:
                    continue
                print( timestampBuckets.url )
                print( timestampBuckets.content.decode() )
                print(e)
                print( timestampBuckets )


            for timestamp in timestampBuckets:

                # timestampedRows.append((timestamp, True, region, resolution, *[None] * 37)) # 37 API filters, there are additional calculated timeseries
                # Keep track of the filter to avoid empty calls because filters vary drastically in their timely availability
                timestampedRows.append( (timestamp, True, region, resolution, *[None] * filterIndex, FLAG, *[None] * (37-filterIndex-1) ) )
                data = get( f"{baseURL}/chart_data/{currentFilter}/{region}/{currentFilter}_{region}_{resolution}_{timestamp}.json")
                data = json.loads( data.content.decode() )

                for tuple in data["series"]:
                    # print(data)  # {…, 'series': [[1420066800000, 12508.5], [1420153200000, None]] }
                    if tuple[1] != None:
                        timestampedRows.append( (tuple[0], False, region, resolution, *[ None ] * 37) )

            insert_optional_data_in_batches( DB_PARAMS, TABLE_NAME_SMARD, timestampedRows, FilterTranslationsList[ filterIndex ] )
            timestampedRows = []


# Then select the timestamps to update one filter column at a time
# But still distinguish between the region and resolution!

rowData = []
for filterIndex, currentFilter in enumerate( allFilters ):

    rows, column_names = get_timestamp_buckets( DB_PARAMS, TABLE_NAME_SMARD, FilterTranslationsList[ filterIndex ] )
    tripleIDs = [ [row[0], row[1], row[2]] for row in rows ]  # [timestamp, region, resolution]

    for timestamp, region, resolution in tripleIDs :
        data = get(
            f"{baseURL}/chart_data/{currentFilter}/{region}/{currentFilter}_{region}_{resolution}_{timestamp}.json" )
        data = json.loads( data.content.decode() )

        for tuple in data[ "series" ]:
            rowData.append( (tuple[ 0 ], False, region, resolution,  # TODO: Merge with first get()?
                             *[None] * filterIndex, tuple[1], *[None] * (37-filterIndex-1) ) )

        insert_optional_data_in_batches( DB_PARAMS, TABLE_NAME_SMARD, rowData, FilterTranslationsList[ filterIndex ] )
        rowData = []


# Some Fields keep their FLAG because the actual bucket returns no value but null for this timestamp
# e.g. curl https://www.smard.de/app/chart_data/4997/DE/4997_DE_day_1388530800000.json




