import json
from datetime import datetime,timedelta,timezone
import pytest
from intelligence_archive import IntelligenceArchive,export_csv
from official_intelligence_reports import discover,SOURCES,document_evidence

def article(title='Coal production rises in Indonesia',url='https://publisher.example/a',days=2,**changes):
 return {'title':title,'description':'Domestic supply update','link':url,'published_at':(datetime.now(timezone.utc)-timedelta(days=days)).isoformat(),'source_name':'Publisher','topics':['cargo_trade'],'commodity_groups':['coal'],**changes}

def test_archive_retains_history_deduplicates_urls_and_records_revisions(tmp_path):
 a=IntelligenceArchive(tmp_path/'archive.sqlite3');a.ingest([article()]);first=a.all()[0]['discovered_at'];a.ingest([article(url='https://publisher.example/a?utm_source=rss',description='Corrected production figure')]);assert len(a.all())==1
 row=a.all()[0];assert row['discovered_at']==first;assert a.get(row['id'])['revision_count']==1
 a.ingest([article(title='Another story',url='https://publisher.example/b')]);assert len(a.all())==2

def test_pagination_basis_filters_future_dates_and_snapshot_export_parity(tmp_path):
 a=IntelligenceArchive(tmp_path/'archive.sqlite3');a.ingest([article(),article(url='https://publisher.example/old',days=40),article(url='https://publisher.example/future',days=-2)])
 rows=a.query(country='Indonesia',commodity_group='coal',days=7);assert len(rows)==1
 snapshot=a.snapshot(rows);a.ingest([article(url='https://publisher.example/new')]);assert len(a.snapshot_rows(snapshot))==1
 assert 'Coal production rises' in export_csv(a.snapshot_rows(snapshot));assert len(a.query(days=90))==3

def test_undated_reports_labelled_and_date_filters_do_not_invent_period(tmp_path):
 a=IntelligenceArchive(tmp_path/'archive.sqlite3');a.ingest([article(content_type='report',published_at=None)])
 assert len(a.query(content_type='report'))==1;assert a.query(start='2026-01-01')==[]

def test_document_review_cannot_fetch_arbitrary_urls():
 import asyncio
 with pytest.raises(ValueError,match='allowlisted'):
  asyncio.run(document_evidence({'link':'http://127.0.0.1/private.pdf'}))

def test_official_reports_discovery_has_real_dates_and_source_lineage():
 rows=discover(SOURCES[0],'<a href="/sites/default/files/media/GTR092426.pdf">Grain Transportation Report</a><a href="https://evil.example/report.pdf">Grain report</a>')
 assert len(rows)==1;assert rows[0]['published_at'].startswith('2026-09-24');assert rows[0]['evidence_level']=='metadata only'

def test_brief_is_source_digest_without_fabricated_claims(tmp_path):
 a=IntelligenceArchive(tmp_path/'archive.sqlite3');a.ingest([article()]);b=a.brief(a.query());g=next(g for g in b['groups'] if g['topic']=='cargo_trade');assert g['article_count']==1;assert g['evidence'][0]['link']=='https://publisher.example/a';assert 'not generated' in b['method']
