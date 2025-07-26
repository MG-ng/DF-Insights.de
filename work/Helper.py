from bidict import bidict
import os
from enum import Enum, unique


TABLE_NAME_SMARD = 'smard_data_collection'
VIEW_NAME_RE_SHARE_EXT_TRADE = 'computed_data_re_share_and_external_trade'
VIEW_NAME_PRICE_CHANGE = 'computed_data_price_change_ger_lux'
FLAG = -1e8

# Reading from environment variable
# If not set, program results in Database error during data insertion:
# connection to server at "localhost" (127.0.0.1), port 5432 failed: fe_sendauth: no password supplied
envPassword = os.getenv( 'DBP' )
db_host = os.getenv( 'DB_HOST', 'localhost' )

DB_PARAMS = {
    'host': db_host,
    'database': 'smard_data',
    'user': 'remoteu',
    'password': envPassword,
    'port': 5432
}

COMPUTED_IDS = {1, 2, 3, 4, 5}
# KEEP SPECIFIC IDS IN REGARD TO THEIR MEANING, they're used in the DB setup
RE_SHARE_ID = 1
ELEC_IMPORT_ID = 2
ELEC_EXPORT_ID = 3
ELEC_PRICE_CHANGE_ABS_ID = 4
ELEC_PRICE_CHANGE_REL_ID = 5
FILTER = {
    "Anteil erneuerbarer Energien (Computed)": RE_SHARE_ID,
    "Importierter Strom (Computed)": ELEC_IMPORT_ID,
    "Exportierter Strom (Computed)": ELEC_EXPORT_ID,
    "DE-LUX Anstieg Strom Absolut (Computed)": ELEC_PRICE_CHANGE_ABS_ID,
    "DE-LUX Anstieg Strom Relativ (Computed)": ELEC_PRICE_CHANGE_REL_ID,
    "Stromerzeugung: Braunkohle": 1223,
    "Stromerzeugung: Kernenergie": 1224,
    "Stromerzeugung: Wind Offshore": 1225,
    "Stromerzeugung: Wasserkraft": 1226,
    "Stromerzeugung: Sonstige Konventionelle": 1227,
    "Stromerzeugung: Sonstige Erneuerbare": 1228,
    "Stromerzeugung: Biomasse": 4066,
    "Stromerzeugung: Wind Onshore": 4067,
    "Stromerzeugung: Photovoltaik": 4068,
    "Stromerzeugung: Steinkohle": 4069,
    "Stromerzeugung: Pumpspeicher": 4070,
    "Stromerzeugung: Erdgas": 4071,
    "Stromverbrauch: Gesamt (Netzlast)": 410,
    "Stromverbrauch: Residuallast": 4359,
    "Stromverbrauch: Pumpspeicher": 4387,
    "Marktpreis: Deutschland/Luxemburg": 4169,
    "Marktpreis: Anrainer DE/LU": 5078,
    "Marktpreis: Belgien": 4996,
    "Marktpreis: Norwegen 2": 4997,
    "Marktpreis: Österreich": 4170,
    "Marktpreis: Dänemark 1": 252,
    "Marktpreis: Dänemark 2": 253,
    "Marktpreis: Frankreich": 254,
    "Marktpreis: Italien (Nord)": 255,
    "Marktpreis: Niederlande": 256,
    "Marktpreis: Polen DON'T USE": 257,  # Unfortunately, the governmental API has 2 fields with the same description
    "Marktpreis: Polen DON'T USE 2": 258,
    "Marktpreis: Schweiz": 259,
    "Marktpreis: Slowenien": 260,
    "Marktpreis: Tschechien": 261,
    "Marktpreis: Ungarn": 262,
    "Prognostizierte Erzeugung: Offshore": 3791,
    "Prognostizierte Erzeugung: Onshore": 123,
    "Prognostizierte Erzeugung: Photovoltaik": 125,
    "Prognostizierte Erzeugung: Sonstige": 715,
    "Prognostizierte Erzeugung: Wind und Photovoltaik": 5097,
    "Prognostizierte Erzeugung: Gesamt": 122
}
FILTER = bidict(FILTER)
# print ( list( FILTER.keys() ) )


FilterTranslationsList = [
    "Share_of_Renewable_Energies_Computed",
    "Imported_Electricity_Computed",
    "Exported_Electricity_Computed",
    "GerLux_Price_Change_Abs_Computed",
    "GerLux_Price_Change_Rel_Computed",
    "Electricity_Production_Lignite",
    "Electricity_Production_Nuclear_Energy",
    "Electricity_Production_Wind_Offshore",
    "Electricity_Production_Hydropower",
    "Electricity_Production_Conventional",
    "Electricity_Production_Renewables",
    "Electricity_Production_Biomass",
    "Electricity_Production_Wind_Onshore",
    "Electricity_Production_Photovoltaics",
    "Electricity_Production_Hard_coal",
    "Electricity_Production_Pumped_storage",
    "Electricity_Production_Natural_gas",
    "Power_Consumption_Total",  # grid_load
    "Power_Consumption_Residual_load",
    "Electricity_Consumption_Pumped_storage",
    "Market_Price_GER_LUX",
    "Market_Price_Adjacent_to_DE_LU",
    "Market_Price_Belgium",
    "Market_Price_Norway_2",
    "Market_Price_Austria",
    "Market_Price_Denmark_1",
    "Market_Price_Denmark_2",
    "Market_Price_France",
    "Market_Price_Italy_North",
    "Market_Price_Netherlands",
    "Market_Price_Poland_no_use",  # Unfortunately, the governmental API has 2 fields with the same description
    "Market_Price_Poland_no_use_2",
    "Market_Price_Swiss",
    "Market_Price_Slovenia",
    "Market_Price_Czech_Republic",
    "Market_Price_Hungary",
    "Production_Forecast_Offshore",
    "Production_Forecast_Onshore",
    "Production_Forecast_Photovoltaics",
    "Production_Forecast_Other",
    "Production_Forecast_Wind_and_PV",
    "Production_Forecast_Total"
]
print( [x for x in FilterTranslationsList if x.find(" ") != -1] )
print()
# print( len( FilterTranslations ) )
assert len( FilterTranslationsList ) == len( FILTER.keys() )

FilterTranslations = bidict( zip( FILTER.keys(), FilterTranslationsList ) )
# print( FilterTranslations)

# List of all possible regions
REGION_LIST = ['DE', 'AT', 'LU', 'DE-LU', 'DE-AT-LU', '50Hertz', 'Amprion', 'TenneT', 'TransnetBW', 'APG', 'Creos']



@unique
class Resolution(Enum):
    QUARTERHOUR = 'quarterhour'
    HOUR = 'hour'
    DAY = 'day'
    WEEK = 'week'
    MONTH = 'month'
    YEAR = 'year'

    @classmethod
    def to_dict( cls ):
        return { item.name: item.value for item in cls }

    @classmethod
    def values( cls ):
        return [ item.value for item in cls ]


def unix_time_duration(duration, resolution):
    durationMs = duration * 1000 * 60 * 15
    if resolution == Resolution.QUARTERHOUR: return durationMs

    durationMs = durationMs * 4
    if resolution == Resolution.HOUR: return durationMs

    durationMs = durationMs * 24
    if resolution == Resolution.DAY: return durationMs

    durationMs = durationMs * 7
    if resolution == Resolution.WEEK: return durationMs

    raise TypeError("Invalid resolution. Must be 'hour', 'day', or 'week'.")

