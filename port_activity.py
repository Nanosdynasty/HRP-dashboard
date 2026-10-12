"""Decoded AIS uploads and auditable, gap-aware polygon visits. No cargo inference."""
from __future__ import annotations
import csv, io, json, math, re, sqlite3, hashlib, time
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, ConfigDict
from shapely.geometry import Point, shape

def utc(value):
    text=str(value).strip()
    # AISStream Time_UTC uses Go's nanosecond UTC serialization.
    if re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)? \+0000 UTC',text):
        text=text.removesuffix(' +0000 UTC')+'+00:00'
    try: dt=datetime.fromisoformat(text.replace('Z','+00:00'))
    except ValueError as e: raise ValueError('Timestamp must be ISO 8601 with a UTC offset') from e
    if dt.tzinfo is None: raise ValueError('Timestamp requires a timezone; local time is not assumed')
    return dt.astimezone(timezone.utc)

def decode_rows(text):
    reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    required={'mmsi','timestamp','lon','lat'}
    if not required.issubset(reader.fieldnames or []): raise ValueError('Required CSV columns: mmsi,timestamp,lon,lat')
    keyed={}; conflicts=set(); duplicate=0; bad=[]
    for i,r in enumerate(reader,2):
        if i>100001: raise ValueError('Maximum 100,000 decoded observations per upload')
        try:
            ident=str(r['mmsi']).strip()
            if not re.fullmatch(r'[1-9][0-9]{8}',ident): raise ValueError('Invalid MMSI')
            stamp=utc(r['timestamp'])
            if stamp.timestamp()>time.time()+86400: raise ValueError('Future observation')
            lon,lat=float(r['lon']),float(r['lat'])
            if not math.isfinite(lon+lat) or not -180<=lon<=180 or not -90<=lat<=90: raise ValueError('Invalid lon/lat')
            def optional(name,maximum):
                s=r.get(name,'')
                if not s: return None
                value=float(s)
                if not math.isfinite(value) or not 0<=value<=maximum: raise ValueError('Invalid '+name)
                return value
            row={'mmsi':ident,'timestamp':stamp.isoformat(),'epoch':stamp.timestamp(),'lon':lon,'lat':lat,
                 'sog_kn':optional('sog_kn',60),'dwt':optional('dwt',1000000),
                 'name':r.get('name','')[:150],'segment':r.get('segment','')[:100] or None,
                 'data_class':r.get('data_class','observed')}
            key=(ident,row['timestamp'])
            if key in keyed:
                if (keyed[key]['lon'],keyed[key]['lat'])!=(lon,lat): conflicts.add(key)
                else: duplicate+=1
            else: keyed[key]=row
        except (ValueError,TypeError) as e: bad.append({'row':i,'reason':str(e)})
    for key in conflicts: keyed.pop(key,None)
    rows=sorted(keyed.values(),key=lambda r:(r['mmsi'],r['epoch']))
    if not rows: raise ValueError('No valid AIS observations remain')
    return rows, {'valid':len(rows),'duplicates_removed':duplicate,'conflicting_times_removed':len(conflicts),
                  'rejected_count':len(bad),'rejected_examples':bad[:20]}

class Zone(BaseModel):
    id: str = Field(min_length=1,max_length=100)
    port_id: str = Field(min_length=1,max_length=100)
    name: str = Field(min_length=1,max_length=150)
    kind: str = Field(pattern='^(port|anchorage)$')
    geometry: dict
    source: str = Field(min_length=1,max_length=500)

class ActivityInput(BaseModel):
    model_config=ConfigDict(allow_inf_nan=False)
    dataset_id: str = Field(max_length=100)
    zones: list[Zone] = Field(default_factory=list,max_length=30)
    start: str | None = None
    end: str | None = None
    port_id: str | None = None
    segment: str | None = None
    dwt_min: float | None = Field(default=None,ge=0,le=1000000)
    dwt_max: float | None = Field(default=None,ge=0,le=1000000)
    status: str = Field(default='all',pattern='^(all|port|anchorage|outside)$')
    max_gap_hours: float = Field(default=6,gt=0,le=48)
    minimum_stay_hours: float = Field(default=0.5,ge=0,le=48)
    snapshot_id: str | None = Field(default=None,max_length=100)

def validate_zones(zones):
    ids=set(); geometries=[]
    for zone in zones:
        if zone.id in ids: raise ValueError('Duplicate zone ID')
        ids.add(zone.id)
        geom=shape(zone.geometry)
        if geom.geom_type not in {'Polygon','MultiPolygon'} or geom.is_empty or not geom.is_valid:
            raise ValueError('Zones must be valid GeoJSON polygons')
        xmin,ymin,xmax,ymax=geom.bounds
        if not (-180<=xmin<xmax<=180 and -90<=ymin<ymax<=90) or xmax-xmin>10 or ymax-ymin>10:
            raise ValueError('Port zones must use lon/lat and span no more than 10 degrees')
        geometries.append((zone,geom))
    return geometries

def analyze(rows,req,metadata):
    begin=utc(req.start).timestamp() if req.start else float('-inf')
    end=utc(req.end).timestamp() if req.end else float('inf')
    if end<begin: raise ValueError('End must follow start')
    if req.dwt_min is not None and req.dwt_max is not None and req.dwt_min>req.dwt_max: raise ValueError('DWT range is reversed')
    zones=validate_zones(req.zones)
    zones=[z for z in zones if not req.port_id or z[0].port_id==req.port_id]
    if req.port_id and not zones: raise ValueError('Selected port has no configured polygon')
    tracks=defaultdict(list)
    for r in rows:
        if not begin<=r['epoch']<=end: continue
        if req.segment and r.get('segment')!=req.segment: continue
        if req.dwt_min is not None and (r.get('dwt') is None or r['dwt']<req.dwt_min): continue
        if req.dwt_max is not None and (r.get('dwt') is None or r['dwt']>req.dwt_max): continue
        tracks[r['mmsi']].append(r)
    events=[]; latest=[]; gaps=0; links=0; trajectory=[]; stops=[]
    for ident,track in tracks.items():
        track.sort(key=lambda r:r['epoch'])
        chunks=[]; chunk=[]
        for r in track:
            if chunk and (r['epoch']-chunk[-1]['epoch'])>req.max_gap_hours*3600:
                gaps+=1; chunks.append(chunk); chunk=[]
            if chunk: links+=1
            chunk.append(r)
        if chunk: chunks.append(chunk)
        last=track[-1]; inside=[z.kind for z,g in zones if g.covers(Point(last['lon'],last['lat']))]
        status='port' if 'port' in inside else 'anchorage' if inside else 'outside'
        if req.status!='all' and status!=req.status: continue
        latest.append({**last,'status':status,'classification':'AIS-observed position',
                       'age_hours':max(0,(time.time()-last['epoch'])/3600)})
        for chunk in chunks:
            trajectory.append({'mmsi':ident,'coordinates':[[r['lon'],r['lat']] for r in chunk],
                               'start':chunk[0]['timestamp'],'end':chunk[-1]['timestamp']})
            for z,geom in zones:
                visit=None; pending_inside=[]; pending_out=[]
                for r in chunk:
                    inside=geom.covers(Point(r['lon'],r['lat']))
                    if inside:
                        pending_out=[]
                        if visit is None:
                            pending_inside.append(r)
                            if len(pending_inside)>=2:
                                visit={'first':pending_inside[0],'last':r,'left_censored':pending_inside[0] is chunk[0], 'observations':2}
                        else: visit['last']=r; visit['observations']+=1
                    else:
                        pending_inside=[]
                        if visit:
                            pending_out.append(r)
                            if len(pending_out)>=2:
                                events.append(visit_row(ident,z,visit,pending_out[0],False,req))
                                visit=None; pending_out=[]
                if visit: events.append(visit_row(ident,z,visit,None,True,req))
            # Simple low-speed runs; no stop is bridged across a transmission gap.
            slow=[]
            for r in chunk+[None]:
                if r and r.get('sog_kn') is not None and r['sog_kn']<=0.5: slow.append(r)
                else:
                    if len(slow)>=2 and slow[-1]['epoch']-slow[0]['epoch']>=req.minimum_stay_hours*3600:
                        from voyage_analysis import polyline_nm
                        if polyline_nm([[x['lon'],x['lat']] for x in slow])<=0.5:
                            stops.append({'mmsi':ident,'start':slow[0]['timestamp'],'end':slow[-1]['timestamp'],
                                          'hours':(slow[-1]['epoch']-slow[0]['epoch'])/3600,'method':'Inferred low-speed stop: <=0.5 kn, path <=0.5 nm; not cargo operations'})
                    slow=[]
    weeks=defaultdict(lambda:{'arrivals':0,'departures':0,'completed_anchorage_hours':[],'completed_vessels':set()})
    for e in events:
        for kind,key in [('arrivals','entry'),('departures','exit')]:
            if e[key]:
                stamp=utc(e[key]); iso=stamp.isocalendar(); weeks[(f'{iso.year}-W{iso.week:02}',e['port_id'],e['kind'])][kind]+=1
        if e['kind']=='anchorage' and not e['left_censored'] and not e['right_censored'] and e['meets_minimum_stay']:
            stamp=utc(e['exit']); iso=stamp.isocalendar(); w=weeks[(f'{iso.year}-W{iso.week:02}',e['port_id'],e['kind'])]
            w['completed_anchorage_hours'].append(e['estimated_hours']); w['completed_vessels'].add(e['mmsi'])
    sufficient=metadata.get('coverage_confirmed') is True and len(latest)>=3 and gaps==0
    weekly=[]
    for (week,port_id,kind),w in sorted(weeks.items()):
        h=w.pop('completed_anchorage_hours'); vessels=w.pop('completed_vessels')
        weekly.append({'week':week,'port_id':port_id,'zone_kind':kind,**w,'completed_anchorage_visits':len(h),
            'mean_anchorage_hours':sum(h)/len(h) if sufficient and len(vessels)>=3 else None})
    return {'positions':latest,'trajectories':trajectory,'events':events,'stops':stops,'weekly':weekly,
            'source':metadata,'rules':{'entry':'Two consecutive inside observations; first inside time. Window-start visits are left-censored.',
                'exit':'Two consecutive outside observations; first outside time. Missing observations never count as departures.',
                'gap':'Split tracks when gap exceeds '+str(req.max_gap_hours)+' hours. Unfinished visits remain right-censored.',
                'waiting':'Anchorage polygon occupancy; not a confirmed berth queue. Completed visit duration requires observed entry and exit.',
                'minimum_stay_hours':req.minimum_stay_hours,'timezone':'UTC','aggregation':'Requires source coverage attestation, >=3 vessels, no gaps and >=3 complete anchorage visits/week.'},
            'quality':{'filtered_vessels':len(latest),'gaps':gaps,'continuous_links':links,'aggregate_congestion_available':any(w['mean_anchorage_hours'] is not None for w in weekly),
                'limitation':'Sample-observed calls are not total port traffic. No arrival forecasts, cargo inference or operational status is supplied.'}}

def visit_row(ident,z,v,exit_row,right,req):
    hours=((exit_row or v['last'])['epoch']-v['first']['epoch'])/3600
    return {'mmsi':ident,'zone_id':z.id,'zone_name':z.name,'port_id':z.port_id,'kind':z.kind,
            'entry':None if v['left_censored'] else v['first']['timestamp'],
            'first_inside':v['first']['timestamp'],'last_inside':v['last']['timestamp'],
            'exit':exit_row['timestamp'] if exit_row else None,'left_censored':v['left_censored'],
            'right_censored':right,'estimated_hours':hours,'meets_minimum_stay':hours>=req.minimum_stay_hours,
            'classification':'Inferred polygon visit','source':z.source,'observations':v['observations']}

class ActivityStore:
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS datasets (id TEXT PRIMARY KEY, metadata TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS positions (dataset_id TEXT, mmsi TEXT, epoch REAL, payload TEXT, PRIMARY KEY(dataset_id,mmsi,epoch))')
            db.execute('CREATE INDEX IF NOT EXISTS idx_activity_time ON positions(dataset_id,epoch)')
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path)
        try:
            yield db; db.commit()
        except Exception: db.rollback(); raise
        finally: db.close()
    def ingest(self,text,source,coverage,confirmed=False):
        rows,quality=decode_rows(text); ident=hashlib.sha256((source+coverage+text).encode()).hexdigest()[:24]
        synthetic=any(r.get('data_class')=='synthetic' for r in rows)
        meta={'id':ident,'source':source,'coverage':coverage,'coverage_confirmed':confirmed and not synthetic,
              'classification':'Synthetic test data — not real vessel observations' if synthetic else 'User supplied decoded AIS; uploader attests permitted use',
              'uploaded_at':datetime.now(timezone.utc).isoformat(),'first_observation':min(r['timestamp'] for r in rows),
              'last_observation':max(r['timestamp'] for r in rows),'rows':len(rows),'quality':quality}
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO datasets VALUES (?,?)',(ident,json.dumps(meta)))
            db.executemany('INSERT OR REPLACE INTO positions VALUES (?,?,?,?)',[(ident,r['mmsi'],r['epoch'],json.dumps(r)) for r in rows])
        return meta
    def load(self,ident):
        with self.db() as db:
            meta=db.execute('SELECT metadata FROM datasets WHERE id=?',(ident,)).fetchone()
            if not meta: raise ValueError('Unknown uploaded dataset')
            rows=[json.loads(r[0]) for r in db.execute('SELECT payload FROM positions WHERE dataset_id=? ORDER BY mmsi,epoch',(ident,))]
        return rows,json.loads(meta[0])

def create_activity_router(store,live_db,base_dir):
    router=APIRouter(prefix='/api/port-activity',tags=['AIS port activity'])
    snapshots={}
    @router.get('/datasets')
    async def datasets():
        with store.db() as db: rows=[json.loads(r[0]) for r in db.execute('SELECT metadata FROM datasets')]
        with sqlite3.connect(live_db) as db:
            count,first,last=db.execute('SELECT COUNT(*),MIN(observed_at),MAX(observed_at) FROM ais_observations').fetchone()
        return {'rows':rows,'live':{'id':'live','source':'Existing AISStream collected history','rows':count,
                 'first_observation':utc(first).isoformat() if first else None,'last_observation':utc(last).isoformat() if last else None,'coverage':'Receiver/feed footprint and selected collection boxes; completeness unknown',
                 'coverage_confirmed':False},'sample_url':'/api/port-activity/sample',
                 'gaps':['DWT/segment filters require supplied vessel metadata. AIS ship type alone does not establish dry-bulk segment.']}
    @router.get('/sample')
    async def sample():
        return Response((base_dir/'data/ais_activity_sample.csv').read_text(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="synthetic-ais-sample.csv"'})
    @router.post('/upload')
    async def upload(file: UploadFile=File(...),source: str=Form(...),coverage: str=Form(...),permitted_use: bool=Form(False),coverage_confirmed: bool=Form(False)):
        if not permitted_use: raise HTTPException(400,'Confirm you are permitted to use this AIS file')
        if not source.strip() or not coverage.strip() or len(source)>500 or len(coverage)>2000: raise HTTPException(400,'Provide bounded source and coverage descriptions')
        body=await file.read(20_000_001)
        if len(body)>20_000_000: raise HTTPException(400,'Maximum 20 MB per upload')
        try: return store.ingest(body.decode('utf-8-sig'),source,coverage,coverage_confirmed)
        except (ValueError,UnicodeError) as e: raise HTTPException(400,str(e)) from e
    def run(req):
        if req.dataset_id=='live':
            clauses=[]; params=[]
            sql_time="julianday(CASE WHEN observed_at LIKE '% +0000 UTC' THEN substr(observed_at,1,26)||'Z' ELSE observed_at END)"
            if req.start:
                clauses.append(sql_time+'>=julianday(?)'); params.append(utc(req.start).isoformat())
            if req.end:
                clauses.append(sql_time+'<=julianday(?)'); params.append(utc(req.end).isoformat())
            where=' WHERE '+' AND '.join(clauses) if clauses else ''
            with sqlite3.connect(live_db) as db:
                raw=db.execute('SELECT mmsi,observed_at,latitude,longitude,sog_kn,vessel_name FROM ais_observations'+where+' ORDER BY observed_at DESC LIMIT 100001',params).fetchall()
            if len(raw)>100000: raise ValueError('Live history exceeds 100,000-row analysis bound. Select a smaller UTC date range or upload a bounded authorized sample.')
            if raw:
                stream=io.StringIO(); writer=csv.writer(stream); writer.writerow(['mmsi','timestamp','lat','lon','sog_kn','name']);writer.writerows(raw)
                rows,quality=decode_rows(stream.getvalue())
            else: rows=[];quality={'valid':0,'rejected_count':0,'duplicates_removed':0}
            meta={'id':'live','source':'Existing AISStream collection','coverage':'Selected receiver boxes; completeness unknown',
                  'coverage_confirmed':False,'rows':len(rows),'quality':quality,'first_observation':min((r['timestamp'] for r in rows),default=None),
                  'last_observation':max((r['timestamp'] for r in rows),default=None),'classification':'AIS-observed history, not guaranteed global coverage'}
        else: rows,meta=store.load(req.dataset_id)
        return analyze(rows,req,meta)
    @router.post('/analyze')
    async def analysis(req: ActivityInput):
        try:
            payload=run(req); ident=secrets.token_hex(16)
            if len(snapshots)>=8: snapshots.pop(next(iter(snapshots)))
            snapshots[ident]=(time.monotonic(),req.model_dump(exclude={'snapshot_id'}),payload)
            return {**payload,'snapshot_id':ident}
        except (ValueError,KeyError,TypeError) as e: raise HTTPException(400,str(e)) from e
    @router.post('/export')
    async def export(req: ActivityInput):
        try:
            if req.snapshot_id:
                snap=snapshots.get(req.snapshot_id)
                if not snap or time.monotonic()-snap[0]>1200: raise HTTPException(409,'Displayed AIS snapshot expired; analyze again before export')
                if snap[1]!=req.model_dump(exclude={'snapshot_id'}): raise HTTPException(409,'Filters differ from displayed snapshot')
                payload=snap[2]
            else: payload=run(req)
        except (ValueError,KeyError,TypeError) as e: raise HTTPException(400,str(e)) from e
        fields=['mmsi','zone_id','zone_name','port_id','kind','entry','first_inside','last_inside','exit','left_censored','right_censored','estimated_hours','meets_minimum_stay','classification','source','observations','dataset_source','dataset_coverage','last_observation','rules']
        stream=io.StringIO(); writer=csv.DictWriter(stream,fieldnames=fields); writer.writeheader()
        for row in payload['events']:
            writer.writerow({**row,'dataset_source':payload['source']['source'],'dataset_coverage':payload['source']['coverage'],
                             'last_observation':payload['source']['last_observation'],'rules':json.dumps(payload['rules'])})
        return Response(stream.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="ais-visit-audit.csv"'})
    return router
