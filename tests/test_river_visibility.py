import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from river_levels import RiverLevelManager,_indonesia_records,linked_canal_records

def test_missing_indonesia_telemetry_is_a_visible_coverage_gap():
 rows=_indonesia_records({'features':[{'geometry':{'coordinates':[109.602343,-.333507]},'properties':{'id':'kapuas','name':'POS DUGA AIR SUKALANTING','last_telemetry':None}}]})
 assert rows[0]['waterbody']=='Kapuas River'
 assert rows[0]['level'] is None and rows[0]['observed_at'] is None
 assert rows[0]['status']=='unavailable'

def test_panama_profile_links_lake_and_draft_without_fabricating_queue():
 lake={'id':'acp-gatun-lake','level':84.7,'level_unit':'ft','observed_at':'2026-09-28T00:00:00-05:00','source_url':'https://evtms-rpts.pancanal.com/eng/h2o/index.html','extra_metrics':{'Neopanamax max draft':'48.0 ft'}}
 canal=next(r for r in linked_canal_records([lake]) if r['id']=='canal-panama')
 assert canal['extra_metrics']['Gatún lake level']=='84.7 ft'
 assert canal['extra_metrics']['Neopanamax max draft']=='48.0 ft'
 assert canal['level'] is None and canal['observed_at'] is None
 assert canal['extra_metrics']['Queue / vessels']=='Not published in this feed'

def test_partial_source_failure_retains_previous_indonesian_observation(tmp_path,monkeypatch):
 manager=RiverLevelManager(tmp_path/'river.json')
 previous={'id':'sihka-old','waterbody':'Musi River','country':'Indonesia','station':'Old','level':1.5,'observed_at':'2026-09-27T08:00:00+07:00'}
 manager.payload={'rows':[previous]}
 for method in ['_fetch_noaa','_fetch_pegel','_fetch_amazon','_fetch_gatun']:
  monkeypatch.setattr(manager,method,AsyncMock(return_value=[]))
 monkeypatch.setattr(manager,'_fetch_indonesia',AsyncMock(side_effect=RuntimeError('Source offline')))
 result=asyncio.run(manager.refresh(force=True))
 row=next(r for r in result['rows'] if r['id']=='sihka-old')
 assert row['observed_at']==previous['observed_at'] and row['level']==1.5
 assert row['source_error']=='Source offline'
 assert 'Indonesia SIHKA' in result['errors'][0]
