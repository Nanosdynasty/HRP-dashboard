import json
from pathlib import Path
import pytest
from port_activity import decode_rows, utc, ActivityInput, ActivityStore, Zone, analyze

def text(points):
    return 'mmsi,timestamp,lon,lat,sog_kn,dwt,segment\n'+'\n'.join(f'900000001,2026-09-01T{hour:02}:00:00Z,{lon},0,0.2,75000,Panamax/Kamsarmax' for hour,lon in points)

def zone():
    return Zone(id='anchor',port_id='demo',name='Test anchorage',kind='anchorage',source='Test polygon',
                geometry={'type':'Polygon','coordinates':[[[0,-1],[1,-1],[1,1],[0,1],[0,-1]]]})

def request(**kw): return ActivityInput(dataset_id='test',zones=[zone()],**kw)
def metadata(): return {'source':'test','coverage':'test footprint','coverage_confirmed':False}

def test_deduplication_conflicts_and_invalid_coordinates():
    body=text([(0,-1),(1,.5),(1,.5),(2,.5)])+'\n900000001,2026-09-01T02:00:00Z,0.8,0,0.2,75000,Panamax/Kamsarmax\n900000001,2026-09-01T03:00:00Z,181,0,,,\ninvalid,2026-09-01T03:00:00Z,1,0,,,'
    rows,q=decode_rows(body)
    assert len(rows)==2
    assert q['duplicates_removed']==1 and q['conflicting_times_removed']==1 and q['rejected_count']==2

def test_timezone_required_and_normalized():
    with pytest.raises(ValueError): utc('2026-09-01T12:00:00')
    assert utc('2026-09-01T12:00:00+05:30').hour==6
    assert utc('2026-09-28 09:57:53.115504383 +0000 UTC').isoformat()=='2026-09-28T09:57:53.115504+00:00'

def test_confirmed_entry_exit_two_observations():
    rows,_=decode_rows(text([(0,-1),(1,.5),(2,.5),(3,.5),(4,-1),(5,-1)]))
    p=analyze(rows,request(),metadata())
    e=p['events'][0]
    assert e['entry']=='2026-09-01T01:00:00+00:00'
    assert e['exit']=='2026-09-01T04:00:00+00:00'
    assert e['estimated_hours']==3
    assert not e['left_censored'] and not e['right_censored']
    assert p['weekly'][0]['arrivals']==1 and p['weekly'][0]['departures']==1
    assert p['weekly'][0]['mean_anchorage_hours'] is None

def test_gap_is_not_departure():
    rows,_=decode_rows(text([(0,-1),(1,.5),(2,.5),(15,-1),(16,-1)]))
    p=analyze(rows,request(),metadata())
    assert p['quality']['gaps']==1
    assert p['events'][0]['exit'] is None
    assert p['events'][0]['right_censored']
    assert sum(w['departures'] for w in p['weekly'])==0
    assert len(p['trajectories'])==2

def test_initial_inside_is_censored_not_arrival():
    rows,_=decode_rows(text([(0,.5),(1,.5),(2,-1),(3,-1)]))
    p=analyze(rows,request(),metadata())
    assert p['events'][0]['entry'] is None
    assert p['events'][0]['left_censored']
    assert p['weekly'][0]['arrivals']==0

def test_dwt_segment_status_and_date_filters():
    rows,_=decode_rows(text([(0,-1),(1,.5),(2,.5)]))
    assert not analyze(rows,request(dwt_min=80000),metadata())['positions']
    assert not analyze(rows,request(segment='Capesize'),metadata())['positions']
    assert not analyze(rows,request(status='outside'),metadata())['positions']
    assert analyze(rows,request(status='anchorage'),metadata())['positions'][0]['status']=='anchorage'
    assert analyze(rows,request(start='2026-09-01T01:00:00Z'),metadata())['events'][0]['left_censored']

def test_invalid_polygon_and_unknown_port():
    rows,_=decode_rows(text([(0,-1),(1,.5)]))
    with pytest.raises(ValueError): analyze(rows,request(port_id='other'),metadata())
    bad=zone();bad.geometry={'type':'Point','coordinates':[0,0]}
    with pytest.raises(ValueError): analyze(rows,ActivityInput(dataset_id='test',zones=[bad]),metadata())

def test_atomic_upload_and_synthetic_guardrail(tmp_path):
    store=ActivityStore(tmp_path/'activity.sqlite3')
    meta=store.ingest(text([(0,-1),(1,.5)]),'Permitted test','Test area')
    rows,m=store.load(meta['id']); assert len(rows)==2
    with pytest.raises(ValueError): store.ingest('invalid','bad','none')
    assert len(store.load(meta['id'])[0])==2
    sample=(Path(__file__).parents[1]/'data/ais_activity_sample.csv').read_text()
    synthetic=store.ingest(sample,'test sample','demo',True)
    assert not synthetic['coverage_confirmed']
    assert synthetic['classification'].startswith('Synthetic')
