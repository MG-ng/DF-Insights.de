from bidict import bidict
import os
from enum import Enum, unique


TABLE_NAME_SMARD = 'smard_data_collection'
TABLE_NAME_OPEN_METEO = 'historical_weather_data_raw'
TABLE_NAME_FORECASTS = 'weather_forecasts_data_raw'
# Der Baustein Gesamt (Netzlast) resultiert aus der Nettostromerzeugung, abzüglich Export-Übertragungsleistung,
# zuzüglich Import-Übertragungsleistung und abzüglich der Einspeicherleistung von Pumpspeicherkraftwerken
# – Datenlieferung erfolgt mit spätestens einer Stunde Verzögerung [Quelle: ENTSO-E].
# Die Residuallast ist definiert als die Netzlast, abzüglich der Einspeisung von Photovoltaik-, Wind Onshore- und Wind Offshore-Anlagen.
VIEW_NAME_RE_SHARE_EXT_TRADE = 'computed_data_re_share_and_external_trade'
VIEW_NAME_PRICE_CHANGE = 'computed_data_price_change_ger_lux'
VIEW_NAME_DUNKELFLAUTEN_STATS = 'computed_data_dunkelflauten_enriched'
VIEW_NAME_HISTORICAL_WEATHER_AGG = 'computed_data_historical_weather_agg'
VIEW_NAME_WEATHER_FORECASTS_AGG = 'computed_data_weather_forecasts_agg'
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

OTHER_THAN_SMARD_FILTER_IDs = { 1, 2, 4, 5, 6, 10, 11, 12, 13, 14, 15, 16, 17 }
# KEEP SPECIFIC IDS IN REGARD TO THEIR MEANING, they're used in the DB setup
RE_SHARE_ID = 1
WIND_SOLAR_ID = 6
ELEC_IMPORT_ID = 2
ELEC_PRICE_CHANGE_ABS_ID = 4
ELEC_PRICE_CHANGE_REL_ID = 5
wind_speed_avg_ID = 10
solar_direct_radiation_ID = 11
solar_diffuse_radiation_ID = 12
repi_power1avg2_ID = 13
repi_30mix_ID = 14
repi_power1avg_ID = 15
repi_square1avg_ID = 16
repi_power_exp_ID = 17
FILTER = {
    "Anteil Photovoltaik-, Wind Onshore- und Wind (Computed)": WIND_SOLAR_ID,
    "Anteil erneuerbarer Energien (Computed)": RE_SHARE_ID,
    "Importierter Strom (Computed) -don't use": ELEC_IMPORT_ID,
    "DE-LUX Anstieg Strom Absolut (Computed)": ELEC_PRICE_CHANGE_ABS_ID,
    "DE-LUX Anstieg Strom Relativ (Computed)": ELEC_PRICE_CHANGE_REL_ID,
	"Wind Geschwindigkeit auf 100m Höhe (Weather)": wind_speed_avg_ID,
	"Direkte Sonneneinstrahlung (Weather)": solar_direct_radiation_ID,
	"Diffuse Sonneneinstrahlung (Weather)": solar_diffuse_radiation_ID,
	"REPI min(speed, 11)^3 & radiation*2": repi_power1avg2_ID,
	"REPI smooth wind limit": repi_power_exp_ID,
	"REPI 30mix": repi_30mix_ID,
	"REPI power1avg": repi_power1avg_ID,
	"REPI sqare1avg": repi_square1avg_ID,
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
    "Share_of_Photovoltaic_Wind_onshore_offshore_Computed",
    "Share_of_Renewable_Energies_Computed",
    "Import_to_Fix",
    "GerLux_Price_Change_Abs_Computed",
    "GerLux_Price_Change_Rel_Computed",
	"wind_speed_100_avg",
	"direct_radiation_avg",
	"diffuse_radiation_avg",
	"repi_power1avg2",
	"repi_power_exp",
	"repi_30mix",
	"repi_power1avg",
	"repi_square1avg",
    "Electricity_Production_Lignite",
    "Electricity_Production_Nuclear_Energy",
    "Electricity_Production_Wind_Offshore",
    "Electricity_Production_Hydropower",
    "Electricity_Production_Other_Conventional",
    "Electricity_Production_Other_Renewables",
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

