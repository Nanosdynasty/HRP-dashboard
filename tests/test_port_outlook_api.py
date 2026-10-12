import csv
import io
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import app as app_module
from port_disruption_outlook import filter_outlook
from tests.test_port_outlook import PORT, build, forecast


def test_outlook_api_filters_provenance_and_exact_csv_snapshot():
    payload = {**build([forecast(weather_condition="Rain")]), "snapshot_id":"snapshot-test", "notice_source_status":{}}
    client = TestClient(app_module.app)
    with patch.object(app_module,"_port_outlook_snapshot",AsyncMock(return_value=payload)):
        response = client.get('/api/port-disruption-outlook',params={"port":"1","country":"AU","operation":"loading/discharge","forecast_window":"0-24","sort":"port_name"})
        assert response.status_code == 200
        data = response.json()
        assert data['rows'] and all(r['port_id']=='1' for r in data['rows'])
        assert all(r['forecast_window']=='0-24' and r['provenance'] for r in data['rows'])
        exported = client.get('/api/port-disruption-outlook/export.csv',params={**data['filters'],"snapshot_id":data['snapshot_id']})
        assert exported.status_code == 200
        csv_rows = list(csv.DictReader(io.StringIO(exported.text)))
        assert [r['row_id'] for r in csv_rows] == [r['row_id'] for r in data['rows']]
        assert exported.headers['x-outlook-snapshot'] == 'snapshot-test'
        assert client.get('/api/port-disruption-outlook?country=GB').json()['rows'] == []
        assert client.get('/api/port-disruption-outlook?forecast_window=invalid').status_code == 422
        assert client.get('/api/port-disruption-outlook/export.csv?snapshot_id=old').status_code == 409
        page = client.get('/api/port-disruption-outlook?limit=1&offset=1').json()
        assert len(page['rows']) == 1
        assert page['total'] == len(payload['rows'])
        assert len(page['map_markers']) == 1
        assert page['map_markers'][0]['port_id'] == '1'


def test_actual_inventory_representative_regions_and_missing_data():
    names = {"PARADIP":"IN","PORT HEDLAND":"AU","RICHARDS BAY":"ZA","ROTTERDAM":"NL","BALTIMORE":"US"}
    engine = app_module.outlook_engine
    inventory = {(p['name'],p['country']) for p in engine.ports}
    assert all(pair in inventory for pair in names.items())
    assert len(inventory) >= 750
    payload = engine.build([],[])
    for name,country in names.items():
        rows = filter_outlook(payload,port=name,country=country)['rows']
        assert rows
        assert all(r['assessment']=='Not assessed' and r['actual_operating_status']=='Not reported' for r in rows)


def test_existing_notice_endpoint_remains_compatible_and_honest():
    client = TestClient(app_module.app)
    response = client.get('/api/port-disruptions')
    assert response.status_code == 200
    data = response.json()
    assert {'active_notices','sources','source_count','methodology','disclaimer'} <= data.keys()
    assert any(s['id']=='india-paradip' for s in data['sources'])
    assert any(s['id']=='pilbara-hedland' for s in data['sources'])
    assert any(s['id']=='india-dgll' for s in data['sources'])
