import json

import requests


base_url = "https://feiertage-api.de/api/"
data = requests.get( base_url + "?nur_daten" ).content

j = json.loads( data.decode('utf8').replace("'", '"') )

print( json.dumps(j, indent=4, sort_keys=True) )


# TODO
