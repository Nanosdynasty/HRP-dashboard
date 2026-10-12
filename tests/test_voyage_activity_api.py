import csv,io,json
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import app as application
from voyage_analysis import polyline_nm,screen_geometry,land_core

client=TestClient(application.app)

def port(name): return str(next(p['id'] for p in application.ports.ports if p['name'].upper()==name.upper()))

def test_real_coal_route_preserves_corridor_and_final_distance():
    request={'origins':[{'port_id':port('RICHARDS BAY')}],'destination':{'port_id':port('PARADIP')},'cargo_tonnes':75000}
    response=client.post('/api/voyage/calculate',json=request)
    assert response.status_code==200,response.text
    row=response.json()['rows'][0]
    assert 4450<row['distance_nm']<4560
    assert row['distance_nm']==polyline_nm(row['coordinates'])
    assert row['tonne_miles']==row['distance_nm']*75000

def test_real_iron_ore_route_to_china_is_screened():
    req={'origins':[{'port_id':port('PORT HEDLAND')}],'destination':{'port_id':port('QINGDAO GANG')},'cargo_tonnes':180000,'commodity':'Iron ore','vessel_segment':'Capesize'}
    response=client.post('/api/voyage/calculate',json=req)
    assert response.status_code==200,response.text
    row=response.json()['rows'][0]
    assert 3000<row['distance_nm']<4500
    screen_geometry(row['coordinates'],land_core(str(application.BASE_DIR/'data/voyage_land_50m.geojson')),row['passages'])
    assert row['tonne_miles']==row['distance_nm']*180000

def test_existing_ais_history_adapter_and_missing_polygons():
    data=client.get('/api/port-activity/datasets')
    assert data.status_code==200
    assert data.json()['live']['coverage_confirmed'] is False
    latest=data.json()['live']['last_observation']
    response=client.post('/api/port-activity/analyze',json={'dataset_id':'live',**({'start':latest,'end':latest} if latest else {})})
    assert response.status_code==200,response.text
    assert response.json()['events']==[]
    assert not response.json()['quality']['aggregate_congestion_available']

def test_ais_upload_auth_and_frozen_export(tmp_path):
    from port_activity import ActivityStore
    original=application.activity_store.path
    # Router references the same store object; isolate the upload fixture from user data.
    isolated=ActivityStore(tmp_path/'isolated.sqlite3')
    sample=(application.BASE_DIR/'data/ais_activity_sample.csv').read_bytes()
    with patch.object(application.activity_store,'path',isolated.path),patch.object(application,'ADMIN_API_TOKEN','test-admin'):
        assert client.post('/api/port-activity/upload',files={'file':('sample.csv',sample)},data={'source':'Synthetic fixture','coverage':'Test only','permitted_use':'true'}).status_code==401
        upload=client.post('/api/port-activity/upload',headers={'X-Admin-Token':'test-admin'},files={'file':('sample.csv',sample)},data={'source':'Synthetic fixture','coverage':'Test only','permitted_use':'true','coverage_confirmed':'true'})
        assert upload.status_code==200,upload.text
        zones=json.loads((application.BASE_DIR/'static/data/ais_sample_zones.json').read_text())
        req={'dataset_id':upload.json()['id'],'zones':zones}
        analysis=client.post('/api/port-activity/analyze',json=req)
        assert analysis.status_code==200,analysis.text
        p=analysis.json();assert len(p['events'])==10
        assert p['source']['classification'].startswith('Synthetic')
        assert all(w['mean_anchorage_hours'] is None for w in p['weekly'])
        req['snapshot_id']=p['snapshot_id']
        export=client.post('/api/port-activity/export',json=req)
        assert export.status_code==200
        rows=list(csv.DictReader(io.StringIO(export.text)))
        assert len(rows)==len(p['events'])
        assert [r['mmsi'] for r in rows]==[r['mmsi'] for r in p['events']]
        req['status']='outside'
        assert client.post('/api/port-activity/export',json=req).status_code==409
    assert application.activity_store.path==original

def test_market_context_has_distinct_grain_and_sources():
    p=client.get('/api/voyage/market-context').json()
    assert p['classification']=='observed official country-level imports'
    assert len(p['rows'])==4 and p['source_url'].startswith('https://coal.gov.in/')
    assert 'not allocated' in p['limitation']
