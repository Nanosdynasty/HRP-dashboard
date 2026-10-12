"""Search observed vessels, independent of the current map and receiver filters."""
import json, re, sqlite3
from contextlib import closing
from port_activity import utc

def init_metadata(db):
    db.execute('CREATE TABLE IF NOT EXISTS ais_search_metadata (mmsi TEXT PRIMARY KEY, imo TEXT, call_sign TEXT, payload TEXT NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_ais_search_imo ON ais_search_metadata(imo)')

def retain_metadata(db,vessels):
    for vessel in vessels:
        ident=str(vessel.get('mmsi') or '')
        if not re.fullmatch(r'[0-9]{9}',ident): continue
        fields={k:vessel[k] for k in ['imo','call_sign','ship_type','name','destination','length_m','width_m'] if vessel.get(k) not in [None,'']}
        if not fields: continue
        previous=db.execute('SELECT payload FROM ais_search_metadata WHERE mmsi=?',(ident,)).fetchone()
        merged={**(json.loads(previous[0]) if previous else {}),**fields}
        db.execute('INSERT OR REPLACE INTO ais_search_metadata VALUES (?,?,?,?)',
                   (ident,str(merged.get('imo') or ''),str(merged.get('call_sign') or ''),json.dumps(merged)))

def matches(vessel,query):
    value=query.strip().casefold()
    ident=re.sub(r'^(imo|mmsi)\s*[:#-]?\s*','',value)
    if ident.isdigit() and len(ident) in [7,9]:
        return str(vessel.get('imo' if len(ident)==7 else 'mmsi') or '')==ident
    tokens=re.findall(r'[a-z0-9]+',value)
    if len(tokens)>1 and tokens[0] in ['mv','mt']: tokens=tokens[1:]
    text=' '.join(str(vessel.get(k) or '') for k in ['name','call_sign']).casefold()
    return bool(tokens) and all(token in text for token in tokens)

def search_observed(path,live,query,limit=50):
    found={str(v['mmsi']):dict(v) for v in live.values() if v.get('mmsi') and matches(v,query) and v.get('lat') is not None and v.get('lon') is not None}
    value=re.sub(r'^(imo|mmsi)\s*[:#-]?\s*','',query.strip().casefold())
    params=[]
    if value.isdigit() and len(value) in [7,9]:
        where='p.mmsi=?' if len(value)==9 else 'm.imo=?';params=[value]
    else:
        tokens=re.findall(r'[a-z0-9]+',value)
        if len(tokens)>1 and tokens[0] in ['mv','mt']: tokens=tokens[1:]
        if not tokens: return []
        where=' AND '.join("LOWER(COALESCE(p.vessel_name,'')||' '||COALESCE(m.call_sign,'')) LIKE ?" for _ in tokens)
        params=['%'+t+'%' for t in tokens]
    with closing(sqlite3.connect(path)) as db:
        rows=db.execute('SELECT p.mmsi,p.observed_at,p.latitude,p.longitude,p.sog_kn,p.cog_deg,p.heading_deg,p.vessel_name,m.payload FROM ais_latest_positions p LEFT JOIN ais_search_metadata m ON p.mmsi=m.mmsi WHERE '+where+' ORDER BY p.observed_at DESC LIMIT ?',params+[limit]).fetchall()
    for r in rows:
        if str(r[0]) in found: continue
        metadata=json.loads(r[8]) if r[8] else {}
        found[str(r[0])]={**metadata,'mmsi':str(r[0]),'last_update':r[1],'lat':r[2],'lon':r[3],
                        'sog_kn':r[4],'cog':r[5],'heading':r[6],'name':r[7] or metadata.get('name',''),'position_source':'retained'}
    output=[]
    for v in found.values():
        try: v['last_update']=utc(v['last_update']).isoformat()
        except (ValueError,KeyError): v['last_update']=None
        if not (-90<=float(v['lat'])<=90 and -180<=float(v['lon'])<=180): continue
        output.append(v)
    output.sort(key=lambda v:v.get('last_update') or '',reverse=True)
    return output[:limit]
