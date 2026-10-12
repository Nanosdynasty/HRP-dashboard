"""Persistent metadata archive and conservative intelligence classification."""
import csv
import hashlib
import io
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

COUNTRIES = {'India': ['india','indian'], 'Indonesia':['indonesia','indonesian'], 'China':['china','chinese'], 'Australia':['australia','australian'], 'Brazil':['brazil','brazilian'], 'South Africa':['south africa'], 'United States':['united states','usda','u.s.'], 'Canada':['canada','canadian'], 'Japan':['japan','japanese'], 'Panama':['panama','gatun'], 'Egypt':['egypt','suez'], 'Singapore':['singapore'], 'Malaysia':['malaysia'], 'Vietnam':['vietnam'], 'Guinea':['guinea'], 'Europe':['europe','european']}
PORTS = ['Port Hedland','Newcastle','Richards Bay','Paradip','Kandla','Mundra','Santos','Tubarao','Qingdao','Rotterdam','Banjarmasin','Balikpapan','Taboneo','Muara Berau','Tanjung Priok','Singapore','Panama Canal','Suez Canal','Beira','Port Sudan']


def stamp(): return datetime.now(timezone.utc).isoformat()
def parse_date(value):
    try:
        d=datetime.fromisoformat(str(value).replace('Z','+00:00'));return d.replace(tzinfo=d.tzinfo or timezone.utc)
    except (ValueError,TypeError): return None


def canonical_url(url):
    p=urlsplit(str(url or ''))
    if p.scheme not in ('https','http'): return ''
    return urlunsplit((p.scheme,p.netloc.lower(),p.path,urlencode([(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith(('utm_','fbclid','gclid'))]),''))


def enrich(row):
    row=dict(row);text=(row.get('title','')+' '+row.get('description','')).lower()
    row['countries']=sorted(set(row.get('countries') or [])|{country for country,terms in COUNTRIES.items() if any(re.search(r'\b'+re.escape(t)+r'\b',text) for t in terms)})
    row['ports']=[name for name in PORTS if re.search(r'\b'+re.escape(name.lower())+r'\b',text)]
    row['vessel_classes']=[v for v in ['capesize','panamax','kamsarmax','supramax','ultramax','handysize'] if v in text]
    row.setdefault('content_type','news');row.setdefault('access_status','Publisher link; metadata available')
    row.setdefault('evidence_level','metadata only');row.setdefault('language','Chinese' if re.search(r'[\u4e00-\u9fff]',text) else 'Indonesian' if re.search(r'batubara|pelabuhan|ekspor',text) else 'Portuguese' if re.search(r'exportação|produção|porto',text) else 'English / language unverified')
    row['canonical_url']=canonical_url(row.get('link'))
    row['id']='article-'+hashlib.sha256((row['canonical_url'] or row.get('title','')).encode()).hexdigest()[:24]
    normalized=re.sub(r'[^a-z0-9]+','',row.get('title','').lower())
    row['event_id']='coverage-'+hashlib.sha256(normalized.encode()).hexdigest()[:16]
    row['event_method']='Same normalized headline; related coverage, not independent confirmation'
    return row


class IntelligenceArchive:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.executescript('CREATE TABLE IF NOT EXISTS articles(id TEXT PRIMARY KEY,published_at TEXT,first_seen TEXT,last_seen TEXT,content_hash TEXT,payload TEXT); CREATE INDEX IF NOT EXISTS publication_date ON articles(published_at); CREATE TABLE IF NOT EXISTS revisions(article_id TEXT,changed_at TEXT,payload TEXT); CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY,created_at TEXT,payload TEXT);')
    @contextmanager
    def connect(self):
        connection=sqlite3.connect(self.path,timeout=15)
        try:
            with connection:yield connection
        finally:connection.close()
    def ingest(self,rows):
        now=stamp();inserted=updated=0
        with self.connect() as c:
            for source in rows:
                row=enrich(source);old=c.execute('SELECT first_seen,content_hash,payload FROM articles WHERE id=?',(row['id'],)).fetchone()
                if old:
                    before=json.loads(old[2]);row={**before,**row}
                    for field in ('document_evidence','document_reviewed_at','evidence_level'):
                        if not source.get('document_reviewed_at') and before.get('document_reviewed_at') and field in before:row[field]=before[field]
                digest=hashlib.sha256(json.dumps({k:v for k,v in row.items() if k not in ('discovered_at','last_seen_at','revision_count')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                if old and old[1]!=digest:
                    c.execute('INSERT INTO revisions VALUES(?,?,?)',(row['id'],now,old[2]));updated+=1
                if not old:inserted+=1
                row['discovered_at']=old[0] if old else now;row['last_seen_at']=now
                c.execute('INSERT OR REPLACE INTO articles VALUES(?,?,?,?,?,?)',(row['id'],row.get('published_at'),row['discovered_at'],now,digest,json.dumps(row,ensure_ascii=False)))
        return {'inserted':inserted,'updated':updated,'received':len(rows)}
    def all(self):
        with self.connect() as c:return [json.loads(r[0]) for r in c.execute('SELECT payload FROM articles ORDER BY published_at DESC')]
    def get(self,article_id):
        with self.connect() as c:
            r=c.execute('SELECT payload FROM articles WHERE id=?',(article_id,)).fetchone()
            if not r:return None
            row=json.loads(r[0]);row['revision_count']=c.execute('SELECT COUNT(*) FROM revisions WHERE article_id=?',(article_id,)).fetchone()[0];return row
    def query(self,*,topic='all',commodity_group='all',query='',days=7,country='',port='',vessel='',publisher='',content_type='',language='',start='',end='',sort='newest',article_ids='',**unused):
        now=datetime.now(timezone.utc);lower=parse_date(start+'T00:00:00+00:00') if start else now-timedelta(days=days) if days else None
        upper=parse_date(end+'T23:59:59+00:00') if end else now
        rows=[]
        for row in self.all():
            if article_ids and row['id'] not in article_ids.split(','):continue
            date=parse_date(row.get('published_at'))
            if date and (date>upper or (lower and date<lower)):continue
            if not date and (start or end or row.get('content_type')!='report'):continue
            if topic!='all' and topic not in row.get('topics',[]):continue
            if commodity_group!='all' and commodity_group not in row.get('commodity_groups',[]):continue
            if country and country not in row.get('countries',[]):continue
            if port and port.casefold() not in ' '.join(row.get('ports',[])).casefold():continue
            if vessel and vessel not in row.get('vessel_classes',[]):continue
            if publisher and publisher!=row.get('source_name'):continue
            if content_type and content_type!=row.get('content_type'):continue
            if language and language!=row.get('language'):continue
            if query and query.casefold() not in ' '.join(str(row.get(k,'')) for k in ['title','description','source_name','countries','ports','commodity_groups','reporting_period']).casefold():continue
            rows.append(row)
        if sort=='relevance':rows.sort(key=lambda r:(r.get('relevance_score',0),r.get('published_at') or ''),reverse=True)
        elif sort=='source':rows.sort(key=lambda r:(r.get('source_name',''),r.get('title','')))
        elif sort=='updated':rows.sort(key=lambda r:r.get('last_seen_at',''),reverse=True)
        return rows
    def snapshot(self,rows):
        body=json.dumps(rows,sort_keys=True,ensure_ascii=False);identity=hashlib.sha256(body.encode()).hexdigest()[:24]
        with self.connect() as c:
            c.execute('INSERT OR REPLACE INTO snapshots VALUES(?,?,?)',(identity,stamp(),body))
            c.execute('DELETE FROM snapshots WHERE created_at<?',((datetime.now(timezone.utc)-timedelta(days=2)).isoformat(),))
        return identity
    def snapshot_rows(self,identity):
        with self.connect() as c:
            r=c.execute('SELECT payload FROM snapshots WHERE id=?',(identity,)).fetchone();return json.loads(r[0]) if r else None
    def brief(self,rows):
        groups=[]
        for topic,label in [('chartering','Freight and chartering'),('cargo_trade','Commodities and trade'),('ports','Ports and infrastructure'),('fleet_snp','Fleet and shipyards'),('policy','Policy and regulation'),('weather','Weather and navigation')]:
            hits=[r for r in rows if topic in r.get('topics',[])];evidence=hits[:8]
            groups.append({'topic':topic,'title':label,'article_count':len(hits),'sources':len({r.get('source_name') for r in hits}),'evidence':[{'id':r['id'],'title':r['title'],'description':r.get('description'),'source_name':r.get('source_name'),'published_at':r.get('published_at'),'link':r['link']} for r in evidence], 'interpretation':'Publisher metadata digest. Full article analysis and causal conclusions are not supplied.'})
        return {'generated_at':stamp(),'method':'Extractive source digest; headlines and publisher descriptions, not generated market forecasts','groups':groups}


def export_csv(rows):
    output=io.StringIO();fields=['id','title','source_name','provider_name','published_at','discovered_at','last_seen_at','content_type','topics','commodity_groups','countries','ports','vessel_classes','language','evidence_level','link','description','event_id']
    writer=csv.DictWriter(output,fieldnames=fields,extrasaction='ignore');writer.writeheader()
    for r in rows:writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in r.items()})
    return output.getvalue()
