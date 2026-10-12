"""Analyst scenarios. Distances are nautical miles; cargo is metric tonnes."""
from __future__ import annotations
import csv, io, json, math, time
from copy import deepcopy
from pathlib import Path
from functools import lru_cache
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, ConfigDict
from shapely.geometry import Point, LineString, box, shape
from shapely.ops import unary_union
from shapely import prepare

SEGMENTS = ['Capesize', 'Panamax/Kamsarmax', 'Supramax/Ultramax', 'Handysize', 'Custom']
PASSAGES = {'automatic': [], 'avoid_suez': ['suez'], 'avoid_panama': ['panama'],
            'avoid_malacca': ['malacca'], 'cape': ['suez']}

class Endpoint(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    port_id: str | None = None
    name: str = Field(default='Coordinate point', max_length=150)
    lon: float | None = Field(default=None, ge=-180, le=180)
    lat: float | None = Field(default=None, ge=-90, le=90)

class VoyageInput(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    origins: list[Endpoint] = Field(min_length=1, max_length=8)
    destination: Endpoint
    intermediate: Endpoint | None = None
    vessel_segment: str = 'Panamax/Kamsarmax'
    commodity: str = Field(default='Coal', max_length=100)
    cargo_tonnes: float = Field(default=75000, gt=0, le=1000000)
    laden_speed_kn: float = Field(default=12, ge=1, le=30)
    ballast_speed_kn: float = Field(default=13, ge=1, le=30)
    port_days: float = Field(default=0, ge=0, le=180)
    passage: str = 'automatic'
    manual_distance_nm: float | None = Field(default=None, gt=0, le=40000)
    manual_source: str = Field(default='', max_length=500)

def arithmetic(distance_nm, tonnes, laden_kn, ballast_kn, port_days):
    return {'distance_nm': distance_nm, 'distance_km': distance_nm * 1.852,
            'laden_sea_days': distance_nm / laden_kn / 24,
            'ballast_return_sea_days': distance_nm / ballast_kn / 24,
            'port_days': port_days, 'laden_total_days': distance_nm / laden_kn / 24 + port_days,
            'round_trip_days': distance_nm / laden_kn / 24 + distance_nm / ballast_kn / 24 + port_days,
            'tonne_miles': tonnes * distance_nm, 'billion_tonne_miles': tonnes * distance_nm / 1e9}

@lru_cache(maxsize=1)
def land_core(path):
    # Inland-only screen: 0.025 degree tolerance acknowledges generalized coastlines.
    raw = json.loads(Path(path).read_text())
    geom=unary_union([shape(f['geometry']) for f in raw['features']]).buffer(-0.025)
    prepare(geom)
    return geom

def screen_geometry(coords, land, passages):
    # These narrow exceptions represent network canal transit, not canal clearance.
    exclusions = []
    if 'suez' in passages: exclusions.append(box(32.15, 29.8, 32.65, 31.5))
    if 'panama' in passages: exclusions.append(box(-79.95, 8.75, -79.45, 9.5))
    for a, b in zip(coords, coords[1:]):
        segments=[[a,b]]
        if abs(a[0]-b[0])>180:
            adjusted=b[0]+(360 if a[0]>0 else -360)
            boundary=180 if a[0]>0 else -180
            if adjusted==a[0]: segments=[[a,[a[0],b[1]]]]
            else:
                latitude=a[1]+(b[1]-a[1])*(boundary-a[0])/(adjusted-a[0])
                segments=[[a,[boundary,latitude]],[[-boundary,latitude],b]]
        lines=[LineString(s) for s in segments if s[0]!=s[1]]
        for line in lines:
            sea_line=line
            for canal in exclusions:
                if sea_line.intersects(canal): sea_line=sea_line.difference(canal)
            if land.intersects(sea_line):
                raise ValueError('Route crosses the generalized inland mask. Use a verified manual distance; no route line is displayed.')

@lru_cache(maxsize=1)
def screened_network(mask_path):
    """Own graph: never mutate the shared graph used by the original voyage tool."""
    import searoute as sr
    land=land_core(mask_path); m=sr.Marnet()
    for a,b,data in sr.setup_M().edges(data=True):
        try: screen_geometry([a,b],land,['suez','panama'])
        except ValueError: continue
        m.add_edge(a,b,**data)
    return m

def reroute_screened(a,b,avoid,mask_path):
    import searoute as sr
    m=deepcopy(screened_network(mask_path)); land=land_core(mask_path)
    # Attach each exact endpoint to the nearest visible sea node, once.
    for p in [a,b]:
        point=(p['lon'],p['lat'])
        candidates=sorted(m.nodes,key=lambda node:polyline_nm([point,node]))[:40]
        attached=0
        for node in candidates:
            distance=polyline_nm([point,node])
            if distance>100: break
            try: screen_geometry([point,node],land,[])
            except ValueError: continue
            m.add_edge(point,node,weight=distance*1.852);attached+=1
            if attached>=3: break
        if not attached: raise ValueError('No screened offshore connector within 100 nm. Select a sea approach or verified manual distance.')
    feature=sr.searoute([a['lon'],a['lat']],[b['lon'],b['lat']],M=m,units='naut',restrictions=list(avoid),return_passages=True,algorithm='astar')
    coords=feature['geometry']['coordinates']; passages=feature['properties'].get('traversed_passages',[])
    if not coords: raise ValueError('No route remains on the screened sea network')
    screen_geometry(coords,land,passages)
    return {'coordinates':coords,'distance_nm':polyline_nm(coords),'passage_ids':passages,'passages':passages,
            'route_confidence':'screened-network','screened_reroute':True}

def create_voyage_router(catalog, compute_route, approach, base_dir, preferred_route=None):
    router = APIRouter(prefix='/api/voyage', tags=['Voyage analysis'])
    cache = {}
    mask_path = str(base_dir / 'data/voyage_land_50m.geojson')

    def resolve(point):
        if point.port_id:
            port = catalog.by_id.get(point.port_id)
            if not port: raise ValueError('Unknown port ID')
            ap = approach(point.port_id)
            lon, lat = (ap['longitude'], ap['latitude']) if ap else (port['lon'], port['lat'])
            sources = port.get('sources') or []
            return {'port_id': point.port_id, 'name': port['name'], 'country': port.get('country_name') or port.get('country'),
                    'country_code':port.get('country'),
                    'lon': float(lon), 'lat': float(lat), 'source': ap.get('source_url') if ap else sources,
                    'last_checked': None, 'source_date': ap.get('source_date') if ap else None,
                    'coordinate_quality': 'reviewed approach' if ap else 'catalogue coordinate; survey date unavailable'}
        if point.lon is None or point.lat is None: raise ValueError('Select a port or enter both longitude and latitude')
        return {**point.model_dump(), 'source': 'Analyst coordinates', 'last_checked': None,
                'coordinate_quality': 'unreviewed analyst input'}

    @router.get('/ports')
    async def port_table(q: str = '', limit: int = 10000):
        rows = []
        for p in catalog.ports:
            if q.casefold() not in (p['name'] + ' ' + str(p.get('country_name') or p.get('country', ''))).casefold(): continue
            r = resolve(Endpoint(port_id=str(p['id'])))
            rows.append(r)
        return {'rows': rows[:min(max(limit, 1), 10000)], 'total': len(rows),
                'limitation': 'Last checked stays unavailable where the bundled catalogue has no survey date.'}

    @router.get('/market-context')
    async def market_context():
        canonical=base_dir/'data/india_coal_master/canonical/coal_imports_by_origin.csv'
        with canonical.open(encoding='utf-8-sig',newline='') as f: raw=list(csv.DictReader(f))
        period=max(r['period'] for r in raw)
        rows=[{'origin_country':r['origin_country'],'total_coal_mt':float(r['total_coal_mt']),
               'status':r['status'],'period':r['period']} for r in raw if r['period']==period and r['origin_country'] in {'Indonesia','Australia','South Africa','Russia'}]
        master=json.loads((base_dir/'data/india_coal_master/india_coal_master.json').read_text(encoding='utf-8'))
        return {'rows':rows,'period':period,'units':'million metric tonnes','classification':'observed official country-level imports',
                'source_url':'https://coal.gov.in/en/public-information/coal-directory','snapshot_generated_at':master.get('generated_at'),
                'lineage':'data/india_coal_master/canonical/coal_imports_by_origin.csv',
                'limitation':'Annual country-to-India imports provide supply context. They are not allocated to the selected ports or multiplied into observed tonne-miles. Port calls, OD changes and vessel availability joins need matching period and port-grain data.'}

    def calculate(req):
        if req.vessel_segment not in SEGMENTS: raise ValueError('Unknown vessel segment')
        if req.passage not in {*PASSAGES, 'via_suez', 'via_panama', 'verified_manual'}: raise ValueError('Unknown passage choice')
        if req.manual_distance_nm is not None and not req.manual_source.strip(): raise ValueError('A verified manual distance needs a source/reference')
        if req.passage in {'via_suez', 'via_panama', 'verified_manual'} and req.manual_distance_nm is None:
            raise ValueError('Forced passage routing is not reliably supported here. Enter a verified manual distance and reference.')
        if req.manual_distance_nm is not None and len(req.origins) != 1:
            raise ValueError('Manual distance applies to one origin at a time')
        if len(req.origins)>1:
            results=[]; errors=[]
            for origin in req.origins:
                try: results.extend(calculate(req.model_copy(update={'origins':[origin]}))['rows'])
                except Exception as exc:
                    try: label=resolve(origin)['name']
                    except ValueError: label=origin.name
                    errors.append({'origin':label,'error':str(exc),'action':'Calculate this origin separately using a reviewed sea coordinate or verified manual distance.'})
            if not results: raise ValueError('; '.join(e['origin']+': '+e['error'] for e in errors))
            return {'rows':results,'errors':errors,'classification':'modeled voyage scenarios','cache_ttl_hours':24}
        dest = resolve(req.destination)
        via = resolve(req.intermediate) if req.intermediate else None
        output = []
        for origin in req.origins:
            start = resolve(origin)
            points = [start] + ([via] if via else []) + [dest]
            warnings = ['Modeled planning estimate, not an actual sailed track or navigational instruction.',
                        'No current canal restrictions, weather, draft clearance, piracy avoidance or charter-party terms are modeled.',
                        'Ballast return assumes the same distance in reverse. Port days are total analyst-entered time.']
            coords, legs, traversed, confidence = [], [], [], []
            for a,b in zip(points, points[1:]):
                if abs(a['lon']-b['lon']) + abs(a['lat']-b['lat']) < 1e-6: raise ValueError('Consecutive endpoints must differ')
            if req.manual_distance_nm is not None:
                distance = req.manual_distance_nm
                minimum=polyline_nm([[p['lon'],p['lat']] for p in points])
                if distance<minimum*0.99: raise ValueError('Manual distance is implausibly shorter than the geodesic minimum through the selected endpoints')
                method = 'Verified distance supplied by analyst'
                warnings.append('Manual distance has no route geometry; intermediate/passages are analyst assertions and are not validated.')
            else:
                land = land_core(mask_path)
                for p in points:
                    if land.contains(Point(p['lon'],p['lat'])):
                        raise ValueError(p['name'] + ' is inland on the generalized mask. Choose a reviewed sea approach or a verified manual distance.')
                for a,b in zip(points, points[1:]):
                    avoid = tuple(['northwest', *PASSAGES[req.passage]])
                    key = (a['lon'],a['lat'],b['lon'],b['lat'],avoid)
                    hit = cache.get(key)
                    if hit and time.monotonic()-hit[0] < 86400: route = hit[1]
                    else:
                        route = preferred_route(a,b,list(avoid)) if preferred_route else None
                        route = route or compute_route(a['lon'],a['lat'],b['lon'],b['lat'],12, list(avoid))
                        try: screen_geometry(route['coordinates'], land, route.get('passage_ids', []))
                        except ValueError: route=reroute_screened(a,b,avoid,mask_path)
                        if not 0.05 <= route['distance_nm'] <= 40000: raise ValueError('Implausible network distance')
                        if len(cache) >= 256: cache.pop(next(iter(cache)))
                        cache[key] = (time.monotonic(), route)
                    coords.extend(route['coordinates'] if not coords else route['coordinates'][1:])
                    legs.append({'origin':a['name'],'destination':b['name'],'distance_nm':route['distance_nm']})
                    traversed.extend(route.get('passages', [])); confidence.append(route.get('route_confidence'))
                    if route.get('route_confidence') == 'low': warnings.append('Long endpoint connector: verify selected coordinates and distance independently.')
                    if route.get('screened_reroute'): warnings.append('A land-crossing candidate was replaced with a route on the screened maritime graph.')
                # Final rendered polyline, rather than rounded per-leg distances, controls arithmetic.
                distance = polyline_nm(coords)
                method = 'searoute 1.6.0 network + endpoint connectors; generalized inland screen'
            result = {**arithmetic(distance,req.cargo_tonnes,req.laden_speed_kn,req.ballast_speed_kn,req.port_days),
                      'origin':start,'destination':dest,'intermediate':via,'coordinates':coords,'legs':legs,
                      'passages':list(dict.fromkeys(traversed)), 'confidence':confidence,'method':method,
                      'warnings':warnings,'inputs':req.model_dump(exclude={'origins','destination','intermediate'}),
                      'calculated_at':datetime.now(timezone.utc).isoformat()}
            output.append(result)
        return {'rows':output,'errors':[],'classification':'modeled voyage scenarios','cache_ttl_hours':24}

    @router.post('/calculate')
    async def calculation(req: VoyageInput):
        try: return calculate(req)
        except ValueError as e: raise HTTPException(400,str(e)) from e
        except Exception as e: raise HTTPException(502,'Network route unavailable. Enter a verified manual distance; no route line is shown.') from e

    @router.post('/export')
    async def export(req: VoyageInput):
        try: payload=calculate(req)
        except ValueError as e: raise HTTPException(400,str(e)) from e
        except Exception as e: raise HTTPException(502,'Network route unavailable; export requires a valid scenario.') from e
        rows=[]
        for r in payload['rows']:
            rows.append({'origin':r['origin']['name'],'destination':r['destination']['name'],
                         'origin_coordinates_lon_lat':json.dumps([r['origin']['lon'],r['origin']['lat']]),
                         'destination_coordinates_lon_lat':json.dumps([r['destination']['lon'],r['destination']['lat']]),
                         'intermediate':json.dumps(r['intermediate']),**r['inputs'],
                         **{k:r[k] for k in arithmetic(1,1,1,1,1)},'method':r['method'],
                         'passages':'; '.join(r['passages']),'warnings':'; '.join(r['warnings']),
                         'coordinate_provenance':json.dumps([r['origin'],r['destination']]),'calculated_at':r['calculated_at'],
                         'status':'calculated','error':''})
        for error in payload.get('errors',[]):
            row={key:'' for key in rows[0]}
            row.update({'origin':error['origin'],'destination':resolve(req.destination)['name'],
                        'status':'not calculated','error':error['error'],'warnings':error['action'],
                        **req.model_dump(exclude={'origins','destination','intermediate'})})
            rows.append(row)
        stream=io.StringIO(); writer=csv.DictWriter(stream,fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
        return Response(stream.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="voyage-tonne-miles.csv"'})
    return router

def polyline_nm(coords):
    def leg(a,b):
        la,lb=math.radians(a[1]),math.radians(b[1]); dlat=lb-la; dlon=math.radians(b[0]-a[0])
        h=math.sin(dlat/2)**2+math.cos(la)*math.cos(lb)*math.sin(dlon/2)**2
        return 3440.065*2*math.asin(math.sqrt(min(1,max(0,h))))
    return sum(leg(a,b) for a,b in zip(coords,coords[1:]))
