from datetime import datetime,timedelta,timezone
from coastal_weather_schema import normalize_coastal_weather_row
from global_cyclones import build_cyclone_records

NOW=datetime(2026,9,28,8,tzinfo=timezone.utc)

def storm(**updates):
 return {'geometry':{'type':'Point','coordinates':[130.9,26.6]},'properties':{'eventid':1,'name':'Tropical Cyclone TEST','iscurrent':'true','todate':'2026-09-28T00:00:00','datemodified':'2026-09-28T07:24:38',**updates}}

def test_active_cyclone_event_time_is_not_forecast_expiry():
 row=build_cyclone_records({'features':[storm()]},{},[],NOW)[0]
 row=normalize_coastal_weather_row(row,fetched_at=NOW.isoformat(),now=NOW)
 assert row['storm_active'] is True
 assert row['source_last_observed_at']=='2026-09-28T00:00:00'
 assert row['valid_to'] is None
 assert row['forecast_expired'] is False
 assert row['freshness_status']=='current'

def test_old_storm_observation_cannot_be_revived_by_recent_download():
 assert not build_cyclone_records({'features':[storm(todate='2026-09-20T00:00:00')]},{},[],NOW)
 row=build_cyclone_records({'features':[storm()]},{},[],NOW)[0]
 assert normalize_coastal_weather_row(row,fetched_at=NOW.isoformat(),now=NOW+timedelta(hours=40))['forecast_expired']

def test_inactive_source_storm_and_stale_successful_check_stay_hidden():
 assert not build_cyclone_records({'features':[storm(iscurrent='false')]},{},[],NOW)
 row=build_cyclone_records({'features':[storm()]},{},[],NOW)[0]
 row['storm_active']=False
 assert normalize_coastal_weather_row(row,fetched_at=NOW.isoformat(),now=NOW)['forecast_expired']
 row['storm_active']=True
 assert normalize_coastal_weather_row(row,fetched_at=(NOW-timedelta(hours=40)).isoformat(),now=NOW)['forecast_expired']
