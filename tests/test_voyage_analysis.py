import csv, io
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import box
from voyage_analysis import arithmetic, Endpoint, VoyageInput, polyline_nm, screen_geometry, create_voyage_router

def test_units_and_tonne_miles():
    r=arithmetic(2400,75000,10,12,2)
    assert r['tonne_miles']==180_000_000
    assert r['billion_tonne_miles']==0.18
    assert r['distance_km']==4444.8
    assert r['laden_sea_days']==10
    assert r['round_trip_days']==pytest.approx(10+2400/12/24+2)

def test_coordinate_order_and_bounds():
    assert Endpoint(lon=120,lat=-20).lon==120
    with pytest.raises(ValueError): Endpoint(lon=-20,lat=120)
    with pytest.raises(ValueError): Endpoint(lon=float('nan'),lat=20)
    assert polyline_nm([[0,0],[1,0]])==pytest.approx(60.04,abs=.02)

def test_land_crossing_rejected():
    with pytest.raises(ValueError): screen_geometry([[-1,0],[2,0]],box(0,-1,1,1),[])
    screen_geometry([[-1,2],[2,2]],box(0,-1,1,1),[])

@pytest.fixture
def client(tmp_path):
    class Catalog:
        ports=[]
        by_id={}
    def route(*args): raise RuntimeError('Unavailable network')
    app=FastAPI();app.include_router(create_voyage_router(Catalog(),route,lambda p:None,tmp_path))
    return TestClient(app)

def manual():
    return {'origins':[{'lon':32.1,'lat':-28.8}],'destination':{'lon':86.78,'lat':20.2},
            'manual_distance_nm':4496,'manual_source':'Analyst NETPAS reference, reviewed route', 'cargo_tonnes':75000}

def test_manual_distance_does_not_draw_fake_line(client):
    req=manual();req['passage']='via_suez'
    response=client.post('/api/voyage/calculate',json=req)
    assert response.status_code==200
    r=response.json()['rows'][0]
    assert r['coordinates']==[]
    assert r['tonne_miles']==4496*75000
    assert r['inputs']['passage']=='via_suez'
    assert 'not validated' in r['warnings'][-1]
    export=client.post('/api/voyage/export',json=req)
    row=list(csv.DictReader(io.StringIO(export.text)))[0]
    assert float(row['tonne_miles'])==r['tonne_miles']
    assert row['manual_source']==req['manual_source']

def test_forced_passage_requires_manual_distance(client):
    req=manual();req['passage']='via_panama';req['manual_distance_nm']=None
    r=client.post('/api/voyage/calculate',json=req)
    assert r.status_code==400 and 'not reliably supported' in r.text

def test_manual_reference_and_identical_endpoints(client):
    req=manual();req['manual_source']=''
    assert client.post('/api/voyage/calculate',json=req).status_code==400
    req=manual();req['destination']=req['origins'][0]
    assert client.post('/api/voyage/calculate',json=req).status_code==400

def test_manual_cannot_reuse_one_distance_for_many_origins(client):
    req=manual();req['origins'].append({'lon':120,'lat':-20})
    assert client.post('/api/voyage/calculate',json=req).status_code==400

def test_unknown_port_not_silently_coordinate_fallback(client):
    req=manual();req['origins']=[{'port_id':'unknown','lon':32.1,'lat':-28.8}]
    assert client.post('/api/voyage/calculate',json=req).status_code==400
