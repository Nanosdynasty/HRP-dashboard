from datetime import datetime,timedelta,timezone
import pytest
from fastapi.testclient import TestClient
import app as application
from news_intelligence import NewsIntelligenceManager,NEWS_RULESET_VERSION

@pytest.fixture
def client(tmp_path,monkeypatch):
 m=NewsIntelligenceManager(tmp_path/'news.json')
 now=datetime.now(timezone.utc).isoformat()
 rows=[{'title':f'Coal production update {i}','description':'India production data','link':f'https://publisher.example/{i}','published_at':now,'source_name':'Publisher','topics':['cargo_trade'],'commodity_groups':['coal']} for i in range(61)]
 m.archive.ingest(rows);m.payload={'ruleset_version':NEWS_RULESET_VERSION,'fetched_at':now,'rows':rows,'providers':[]}
 monkeypatch.setattr(application,'news_intelligence_manager',m)
 return TestClient(application.app)

def test_api_can_page_every_matching_row_and_export_exact_snapshot(client):
 p=client.get('/api/news?country=India&page_size=25&page=2').json();assert p['total']==61;assert len(p['rows'])==25;assert p['pages']==3;assert p['page']==2
 export=client.get('/api/news/export.csv',params={'snapshot_id':p['snapshot_id']});assert export.status_code==200;assert len(export.text.splitlines())==62
 assert client.get('/api/news/export.csv?snapshot_id=missing').status_code==409

def test_api_search_brief_and_detail_sources(client):
 p=client.get('/api/news?q=update%2060').json();assert p['total']==1
 brief=client.get('/api/news/brief',params={'snapshot_id':p['snapshot_id']});assert brief.status_code==200
 assert client.get('/api/news/articles/'+p['rows'][0]['id']).json()['source_name']=='Publisher'
 assert client.get('/api/news?country=Indonesia').json()['total']==0
