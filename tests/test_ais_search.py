import sqlite3,json
from ais_search import init_metadata,retain_metadata,search_observed,matches

def dbfile(tmp_path):
    path=tmp_path/'ais.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE ais_latest_positions(mmsi TEXT PRIMARY KEY,observed_at TEXT,latitude REAL,longitude REAL,sog_kn REAL,cog_deg REAL,heading_deg REAL,vessel_name TEXT)')
        init_metadata(db)
        db.execute('INSERT INTO ais_latest_positions VALUES (?,?,?,?,?,?,?,?)',('900000001','2026-09-28 10:00:00.123456789 +0000 UTC',-35,-70,12,45,45,'TEST ACE'))
        retain_metadata(db,[{'mmsi':'900000001','imo':'9000007','call_sign':'TEST9','ship_type':70}])
    return path

def test_full_database_imo_lookup_survives_empty_live_cache(tmp_path):
    p=dbfile(tmp_path);rows=search_observed(p,{},'IMO 9000007')
    assert len(rows)==1 and rows[0]['mmsi']=='900000001'
    assert rows[0]['lon']==-70
    assert rows[0]['last_update']=='2026-09-28T10:00:00.123456+00:00'

def test_names_mmsi_callsign_and_prefix(tmp_path):
    p=dbfile(tmp_path)
    for query in ['TEST ACE','MV TEST ACE','900000001','TEST9']:
        assert len(search_observed(p,{},query))==1
    assert search_observed(p,{},'9713466')==[]
    assert not matches({'mmsi':'129000007','name':''},'9000007')

def test_live_result_wins_and_metadata_updates_preserve_known_imo(tmp_path):
    p=dbfile(tmp_path)
    with sqlite3.connect(p) as db:retain_metadata(db,[{'mmsi':'900000001','name':'TEST ACE RENAMED'}])
    live={'900000001':{'mmsi':'900000001','imo':'9000007','name':'TEST ACE','lat':-34,'lon':-71,'last_update':'2026-09-28T11:00:00Z'}}
    rows=search_observed(p,live,'9000007')
    assert len(rows)==1 and rows[0]['lon']==-71

def test_static_data_without_position_does_not_make_up_marker(tmp_path):
    p=dbfile(tmp_path)
    with sqlite3.connect(p) as db:retain_metadata(db,[{'mmsi':'900000002','imo':'9000008','name':'NO POSITION'}])
    assert search_observed(p,{},'9000008')==[]
