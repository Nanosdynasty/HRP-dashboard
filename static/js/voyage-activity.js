/* Reuses the existing navigation and Leaflet, with independent analyst map layers. */
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => Number(value).toLocaleString(undefined, {maximumFractionDigits:2});
  const id = name => document.getElementById(name);
  const model = {ports:[], voyage:null, voyageInput:null, activity:null, activityInput:null, maps:{}, layers:{}};
  const segments = ['Capesize','Panamax/Kamsarmax','Supramax/Ultramax','Handysize','Custom'];
  async function api(path, body, raw=false) {
    const response = await fetch(path, body ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {});
    if (!response.ok) { const text=await response.text(); let detail=text; try {detail=JSON.parse(text).detail;} catch {} throw new Error(typeof detail==='string'?detail:JSON.stringify(detail)); }
    return raw ? response.blob() : response.json();
  }
  function download(blob,name) { const link=document.createElement('a'); link.href=URL.createObjectURL(blob); link.download=name; link.click(); setTimeout(()=>URL.revokeObjectURL(link.href),1000); }
  const field=(label,name,content)=>`<label>${esc(label)}${content || `<input id="${name}" />`}</label>`;
  function map(name) {
    if (!model.maps[name]) {
      const m=L.map(name,{preferCanvas:true}).setView([4,80],3);
      L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',{attribution:'© OpenStreetMap contributors © CARTO',maxZoom:18}).addTo(m);
      model.maps[name]=m; model.layers[name]=L.layerGroup().addTo(m);
    }
    setTimeout(()=>model.maps[name].invalidateSize(),0);
    return [model.maps[name],model.layers[name]];
  }
  function routeLines(coords) {
    const chunks=[]; let chunk=[];
    for (const p of coords) { if(chunk.length && Math.abs(p[0]-chunk.at(-1)[0])>180) {chunks.push(chunk);chunk=[];} chunk.push(p); }
    if(chunk.length) chunks.push(chunk); return chunks;
  }
  function endpoint(text) {
    text=text.trim(); const p=model.ports.find(p=>p.label===text);
    if(p) return {port_id:p.port_id};
    const parts=text.split(',').map(v=>v.trim());
    if(parts.length===2 && parts.every(v=>v!=='' && Number.isFinite(Number(v)))) return {lon:Number(parts[0]),lat:Number(parts[1]),name:text};
    throw new Error('Choose a country-qualified port from the list, or enter longitude, latitude.');
  }
  async function ports() {
    if(model.ports.length) return;
    const p=await api('/api/voyage/ports'); model.ports=p.rows.map(p=>({...p,label:`${p.name} (${p.country || 'unknown'}) [${p.port_id}]`}));
    id('analyst-ports').innerHTML=model.ports.map(p=>`<option value="${esc(p.label)}"></option>`).join('');
  }
  function choose(name,country='') { return model.ports.find(p=>p.name.toUpperCase()===name.toUpperCase() && (!country || p.country_code===country))?.label || ''; }
  function voyageRequest() {
    return {origins:id('va-origins').value.split('\n').filter(v=>v.trim()).map(endpoint),destination:endpoint(id('va-destination').value),
      intermediate:id('va-intermediate').value.trim()?endpoint(id('va-intermediate').value):null,
      vessel_segment:id('va-segment').value,commodity:id('va-commodity').value,cargo_tonnes:Number(id('va-tonnes').value),
      laden_speed_kn:Number(id('va-laden').value),ballast_speed_kn:Number(id('va-ballast').value),port_days:Number(id('va-days').value),
      passage:id('va-passage').value,manual_distance_nm:id('va-manual').value?Number(id('va-manual').value):null,manual_source:id('va-source').value};
  }
  function chart(rows,label,value,name) {
    if(!rows.length) return '<p>No comparable observations in this filter.</p>';
    const max=Math.max(...rows.map(r=>Number(r[value])||0),1);
    return `<div class="analyst-bars" aria-label="${esc(name)}">${rows.map(r=>`<div><span>${esc(r[label])}</span><i style="width:${Math.max(0,100*(Number(r[value])||0)/max)}%"></i><b>${r[value]===null?'Not assessed':number(r[value])}</b></div>`).join('')}</div>`;
  }
  function renderVoyage(payload) {
    const rows=payload.rows; const [m,layer]=map('va-map');layer.clearLayers();const points=[];
    rows.forEach((r,index)=>{
      const color=['#003b71','#af2630','#976b16','#297868'][index%4];
      for(const chunk of routeLines(r.coordinates)) L.polyline(chunk.map(p=>[p[1],p[0]]),{color,weight:3}).addTo(layer);
      for(const p of [r.origin,r.destination]) {const pt=[p.lat,p.lon];points.push(pt);L.circleMarker(pt,{color,radius:5}).bindPopup(esc(p.name)).addTo(layer);}
    });
    if(points.length) m.fitBounds(L.latLngBounds(points),{padding:[30,30]});
    const r=rows[0];
    id('va-result').innerHTML=`<div class="analyst-kpis">${[['Sea distance',number(r.distance_nm)+' nm'],['Laden sea time',number(r.laden_sea_days)+' days'],['Cargo demand',number(r.billion_tonne_miles)+' billion tonne-nm'],['Round-trip scenario',number(r.round_trip_days)+' days']].map(([l,v])=>`<article><span>${l}</span><strong>${v}</strong></article>`).join('')}</div>
      <h2>Origin comparison</h2>${(payload.errors || []).map(e=>`<p role="alert"><strong>${esc(e.origin)}</strong>: ${esc(e.error)} ${esc(e.action)}</p>`).join('')}${chart(rows.map(r=>({origin:r.origin.name,tonne_miles:r.tonne_miles})),'origin','tonne_miles','Modeled tonne-nautical-miles by origin')}
      <div class="analyst-table"><table><thead><tr><th>Origin</th><th>Destination</th><th>Distance nm</th><th>Laden days</th><th>Ballast return days</th><th>Port days</th><th>Laden total days</th><th>Tonne-nm</th><th>Passages</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.origin.name)}</td><td>${esc(r.destination.name)}</td>${[r.distance_nm,r.laden_sea_days,r.ballast_return_sea_days,r.port_days,r.laden_total_days,r.tonne_miles].map(v=>`<td>${number(v)}</td>`).join('')}<td>${esc(r.passages.join(', ') || 'None reported / manual')}</td></tr>`).join('')}</tbody></table></div>
      <details open><summary>Calculation and sources</summary><p>Tonne-nautical-miles = cargo tonnes × laden distance nm. Sea days = nm ÷ knots ÷ 24. Round trip assumes the same distance for ballast return; port days are counted once. Edit the inputs above to recalculate.</p>${rows.map(r=>`<p><strong>${esc(r.origin.name)}</strong> · ${esc(r.method)} · ${esc(r.calculated_at)}<br>Coordinate quality: ${esc(r.origin.coordinate_quality)} / ${esc(r.destination.coordinate_quality)}. Last checked: ${esc(r.origin.last_checked || 'not recorded')} / ${esc(r.destination.last_checked || 'not recorded')}.</p>`).join('')}<ul>${[...new Set(rows.flatMap(r=>r.warnings))].map(w=>`<li>${esc(w)}</li>`).join('')}</ul></details>`;
    id('va-export').disabled=false;
  }
  async function initVoyage() {
    if(id('va-form')) {map('va-map');return;}
    id('voyage-analysis-surface').innerHTML=`<header><h1>Voyage &amp; Tonne-Miles</h1><p>Model a cargo voyage or compare up to eight origins. Tonne-miles use nautical miles.</p></header>
      <datalist id="analyst-ports"></datalist><form id="va-form" class="analyst-form">
      ${field('Origin port or longitude, latitude','', '<textarea id="va-origins" rows="3" placeholder="One origin per line" required></textarea>')}
      ${field('Destination port or longitude, latitude','', '<input id="va-destination" list="analyst-ports" required />')}
      ${field('Optional intermediate port or longitude, latitude','', '<input id="va-intermediate" list="analyst-ports" />')}
      ${field('Add catalogue origin','', '<input id="va-add-origin" list="analyst-ports" placeholder="Choose a port to append" />')}
      ${field('Vessel segment','',`<select id="va-segment">${segments.map(s=>`<option ${s==='Panamax/Kamsarmax'?'selected':''}>${s}</option>`).join('')}</select>`)}
      ${field('Commodity','', '<input id="va-commodity" value="Coal" required />')}
      ${field('Cargo tonnes','', '<input id="va-tonnes" type="number" min="1" max="1000000" value="75000" required />')}
      ${field('Laden speed, knots','', '<input id="va-laden" type="number" min="1" max="30" step="0.1" value="12" required />')}
      ${field('Ballast speed, knots','', '<input id="va-ballast" type="number" min="1" max="30" step="0.1" value="13" required />')}
      ${field('Total port days','', '<input id="va-days" type="number" min="0" max="180" step="0.1" value="2" required />')}
      ${field('Routing choice','', '<select id="va-passage"><option value="automatic">Network shortest route</option><option value="avoid_suez">Avoid Suez</option><option value="avoid_panama">Avoid Panama</option><option value="avoid_malacca">Avoid Malacca</option><option value="cape">Cape alternative (excludes Suez; verify passage)</option><option value="via_suez">Require Suez — manual distance</option><option value="via_panama">Require Panama — manual distance</option><option value="verified_manual">Verified manual distance</option></select>')}
      ${field('Verified manual distance, nm','', '<input id="va-manual" type="number" min="0.1" max="40000" step="0.1" />')}
      ${field('Manual distance source/reference','', '<input id="va-source" placeholder="Provider, passage, version/date" />')}
      <div class="analyst-actions"><button type="submit" class="primary-button">Calculate / compare</button><button type="button" id="va-export" disabled>CSV inputs &amp; results</button><button type="button" id="va-coal">Coal → India</button><button type="button" id="va-ore">Iron ore → China</button></div></form>
      <p id="va-message" role="status">Loading port catalogue…</p><div id="va-result"></div><div id="va-map" class="analyst-map" aria-label="Modeled voyage routes"></div><div id="va-market"></div>`;
    await ports();
    id('va-add-origin').addEventListener('change',()=>{if(model.ports.some(p=>p.label===id('va-add-origin').value)){id('va-origins').value += (id('va-origins').value?'\n':'')+id('va-add-origin').value;id('va-add-origin').value='';}});
    id('va-coal').onclick=()=>{id('va-origins').value=[choose('Samarinda Anchorage Port','ID'),choose('NEWCASTLE','AU'),choose('RICHARDS BAY','ZA'),choose('VOSTOCHNYY','RU')].filter(Boolean).join('\n');id('va-destination').value=choose('PARADIP','IN');id('va-commodity').value='Coal';id('va-tonnes').value=75000;};
    id('va-ore').onclick=()=>{id('va-origins').value=choose('PORT HEDLAND');id('va-destination').value=choose('QINGDAO GANG') || choose('QINGDAO') || '120.2,35.95';id('va-commodity').value='Iron ore';id('va-tonnes').value=180000;id('va-segment').value='Capesize';};
    id('va-origins').value=choose('RICHARDS BAY');id('va-destination').value=choose('PARADIP');id('va-message').textContent='Choose ports or enter longitude, latitude. Forced passages require a verified manual distance.';map('va-map');
    id('va-form').onsubmit=async e=>{e.preventDefault();id('va-message').textContent='Calculating…';id('va-export').disabled=true;const [m,layer]=map('va-map');layer.clearLayers();id('va-result').innerHTML='';try{const input=voyageRequest();const payload=await api('/api/voyage/calculate',input);model.voyage=payload;model.voyageInput=input;renderVoyage(payload);id('va-message').textContent=`${payload.rows.length} modeled scenario(s).`; }catch(error){id('va-message').textContent=error.message;}};
    id('va-export').onclick=async()=>{try{download(await api('/api/voyage/export',model.voyageInput,true),'voyage-tonne-miles.csv');}catch(e){id('va-message').textContent=e.message;}};
    if (window.hrpCan && !window.hrpCan('india_coal')) id('va-market').hidden=true;
    else try {const p=await api('/api/voyage/market-context'); id('va-market').innerHTML=`<h2>Observed India coal imports by origin</h2><p>${esc(p.limitation)}</p>${chart(p.rows,'origin_country','total_coal_mt','Official annual imports, million tonnes')}<p>${esc(p.period)} · ${esc(p.units)} · <a href="${esc(p.source_url)}" target="_blank" rel="noopener">Ministry source catalogue</a> · Snapshot ${esc(p.snapshot_generated_at)}</p>`;} catch(e){id('va-market').textContent='Market context unavailable: '+e.message;}
  }
  function activityRequest() {
    return {dataset_id:id('pa-dataset').value,zones:JSON.parse(id('pa-zones').value || '[]'),start:id('pa-start').value?new Date(id('pa-start').value+'Z').toISOString():null,
      end:id('pa-end').value?new Date(id('pa-end').value+'Z').toISOString():null,port_id:id('pa-port').value || null,segment:id('pa-segment').value || null,
      dwt_min:id('pa-dwt-min').value?Number(id('pa-dwt-min').value):null,dwt_max:id('pa-dwt-max').value?Number(id('pa-dwt-max').value):null,
      status:id('pa-status').value,max_gap_hours:Number(id('pa-gap').value),minimum_stay_hours:Number(id('pa-stay').value)};
  }
  async function datasets() {
    const p=await api('/api/port-activity/datasets'); id('pa-dataset').innerHTML='<option value="">Select uploaded dataset</option>'+p.rows.map(r=>`<option value="${esc(r.id)}">${esc(r.source)} · ${r.rows} observations · ${esc(r.last_observation)}</option>`).join('')+`<option value="live">Collected AISStream history · ${p.live.rows} observations</option>`;
    id('pa-feed').textContent=`Live collection coverage: ${p.live.coverage}. Latest observation: ${p.live.last_observation || 'none'}. ${p.gaps.join(' ')}`;
    id('pa-dataset').onchange=()=>{
      id('pa-start').value='';id('pa-end').value='';
      if(id('pa-dataset').value!=='live' || !p.live.last_observation) return;
      const last=new Date(p.live.last_observation);
      if(Number.isFinite(last.getTime())) {
        id('pa-start').value=new Date(last.getTime()-3600000).toISOString().slice(0,16);
        id('pa-end').value=new Date(last.getTime()+60000).toISOString().slice(0,16);
      }
    };
    return p;
  }
  function renderActivity(p) {
    const [m,layer]=map('pa-map');layer.clearLayers();const points=[];
    for(const z of model.activityInput.zones) L.geoJSON({type:'Feature',properties:{},geometry:z.geometry},{style:{color:z.kind==='port'?'#003b71':'#976b16',weight:2}}).bindPopup(esc(z.name)).addTo(layer);
    for(const t of p.trajectories) for(const c of routeLines(t.coordinates)) if(c.length>1) L.polyline(c.map(p=>[p[1],p[0]]),{color:'#8298ac',weight:1}).addTo(layer);
    for(const r of p.positions) {points.push([r.lat,r.lon]);L.circleMarker([r.lat,r.lon],{radius:5,color:r.status==='anchorage'?'#976b16':'#003b71'}).bindPopup(`${esc(r.name || r.mmsi)}<br>AIS-observed position · ${esc(r.timestamp)}<br>${esc(r.status)} · ${number(r.age_hours)} hours old`).addTo(layer);}
    if(points.length)m.fitBounds(L.latLngBounds(points),{padding:[30,30],maxZoom:12});
    id('pa-result').innerHTML=`<p><strong>${esc(p.source.source)}</strong> · ${esc(p.source.classification)}<br>${esc(p.source.coverage)} · ${esc(p.source.first_observation)} to ${esc(p.source.last_observation)} · Uploaded ${esc(p.source.uploaded_at || 'existing collector')}</p>
      <div class="analyst-kpis">${[['Vessels observed',p.positions.length],['Transmission gaps',p.quality.gaps],['Inferred polygon visits',p.events.length],['Aggregate congestion',p.quality.aggregate_congestion_available?'Eligible weeks only':'Not assessed']].map(([l,v])=>`<article><span>${l}</span><strong>${esc(v)}</strong></article>`).join('')}</div>
      <h2>Sample-observed weekly activity</h2>${chart(p.weekly.map(r=>({...r,label:`${r.week} ${r.zone_kind} ${r.port_id}`})),'label','arrivals','Inferred arrivals by polygon and week')}
      <div class="analyst-table"><table><thead><tr><th>Week / port / zone</th><th>Inferred arrivals</th><th>Inferred departures</th><th>Complete anchorage visits</th><th>Mean anchorage hours</th></tr></thead><tbody>${p.weekly.map(r=>`<tr><td>${esc(r.week)} / ${esc(r.port_id)} / ${esc(r.zone_kind)}</td><td>${r.arrivals}</td><td>${r.departures}</td><td>${r.completed_anchorage_visits}</td><td>${r.mean_anchorage_hours===null?'Not assessed':number(r.mean_anchorage_hours)}</td></tr>`).join('')}</tbody></table></div>
      <h2>Vessel visit audit</h2><div class="analyst-table"><table><thead><tr><th>MMSI</th><th>Polygon</th><th>First inside UTC</th><th>Exit UTC</th><th>Estimated hours</th><th>Incomplete</th></tr></thead><tbody>${p.events.slice(0,500).map(r=>`<tr><td>${esc(r.mmsi)}</td><td>${esc(r.zone_name)}</td><td>${esc(r.first_inside)}</td><td>${esc(r.exit || 'Not observed')}</td><td>${number(r.estimated_hours)}</td><td>${r.left_censored?'Entry unknown; ':''}${r.right_censored?'Exit unknown':''}</td></tr>`).join('')}</tbody></table></div><p>Displaying ${Math.min(500,p.events.length)} of ${p.events.length} visits. CSV exports all filtered visits. Low-speed stops: ${p.stops.length}.</p>
      <details open><summary>Exact inference rules and coverage</summary>${Object.entries(p.rules).map(([k,v])=>`<p><strong>${esc(k)}</strong>: ${esc(v)}</p>`).join('')}<p>${esc(p.quality.limitation)}</p><p>Upload checks: ${esc(JSON.stringify(p.source.quality || {}))}</p></details>`;
    id('pa-export').disabled=false;
  }
  async function initActivity() {
    if(id('pa-form')){map('pa-map');return;}
    id('port-activity-surface').innerHTML=`<header><h1>AIS &amp; Port Activity</h1><p>Observed positions and inferred polygon visits. Coverage is disclosed for every dataset.</p></header>
      <div id="pa-map" class="analyst-map" aria-label="Observed AIS positions and inferred tracks"></div>
      <details><summary>Upload permitted decoded AIS data</summary><form id="pa-upload" class="analyst-form">
      ${field('Decoded CSV','', '<input id="pa-file" type="file" accept=".csv" required />')}${field('Source / provider and licence','', '<input id="pa-source" required />')}${field('Coverage: area, period, receiver completeness','', '<input id="pa-coverage" required />')}
      <label><input id="pa-permitted" type="checkbox" required /> I am permitted to use this data</label><label><input id="pa-complete" type="checkbox" /> Source evidence confirms continuous coverage</label><button class="primary-button">Upload and validate</button></form>
      <p>Columns: mmsi,timestamp,lon,lat; optional sog_kn,dwt,name,segment. ISO timestamps require offsets. DWT is tonnes; speed is knots. <a href="/api/port-activity/sample">Download synthetic test sample</a> (not real vessel observations).</p></details>
      <p id="pa-feed"></p><form id="pa-form" class="analyst-form">
      ${field('Dataset','', '<select id="pa-dataset" required></select>')}${field('Start UTC','', '<input id="pa-start" type="datetime-local" />')}${field('End UTC','', '<input id="pa-end" type="datetime-local" />')}
      ${field('Port ID filter','', '<input id="pa-port" placeholder="Requires a matching configured polygon" />')}${field('Vessel segment','',`<select id="pa-segment"><option value="">All supplied segments</option>${segments.map(s=>`<option>${s}</option>`).join('')}</select>`)}
      ${field('Minimum DWT, tonnes','', '<input id="pa-dwt-min" type="number" min="0" />')}${field('Maximum DWT, tonnes','', '<input id="pa-dwt-max" type="number" min="0" />')}
      ${field('Latest observed polygon status','', '<select id="pa-status"><option value="all">All</option><option value="port">Inside port</option><option value="anchorage">Inside anchorage</option><option value="outside">Outside configured polygons</option></select>')}
      ${field('Maximum gap, hours','', '<input id="pa-gap" type="number" min="0.1" max="48" step="0.1" value="6" />')}${field('Minimum stay, hours','', '<input id="pa-stay" type="number" min="0" max="48" step="0.1" value="0.5" />')}
      <label class="analyst-wide">Polygon definitions: JSON array, GeoJSON longitude/latitude<textarea id="pa-zones" rows="5">[]</textarea></label>
      <div class="analyst-actions"><button class="primary-button">Analyze filtered history</button><button type="button" id="pa-export" disabled>CSV vessel audit</button><button type="button" id="pa-sample-zones">Synthetic sample polygons</button><label>Load polygon JSON<input id="pa-zone-file" type="file" accept=".json" /></label></div></form>
      <p id="pa-message" role="status">No official port polygons are assumed. Configure reviewed polygons before interpreting visits.</p><div id="pa-result"></div>`;
    const available=await datasets();map('pa-map');
    id('pa-sample-zones').onclick=async()=>{try{id('pa-zones').value=JSON.stringify(await api('/static/data/ais_sample_zones.json'),null,2);}catch(e){id('pa-message').textContent=e.message;}};
    id('pa-zone-file').onchange=async()=>{try{id('pa-zones').value=JSON.stringify(JSON.parse(await id('pa-zone-file').files[0].text()),null,2);}catch(e){id('pa-message').textContent='Invalid polygon file: '+e.message;}};
    id('pa-upload').onsubmit=async e=>{e.preventDefault();try{const f=new FormData();f.append('file',id('pa-file').files[0]);f.append('source',id('pa-source').value);f.append('coverage',id('pa-coverage').value);f.append('permitted_use',id('pa-permitted').checked);f.append('coverage_confirmed',id('pa-complete').checked);let response=await fetch('/api/port-activity/upload',{method:'POST',body:f});
      if(response.status===401){const token=window.prompt('Administrator token for AIS upload');if(token) response=await fetch('/api/port-activity/upload',{method:'POST',headers:{'X-Admin-Token':token},body:f});}
      const p=await response.json();if(!response.ok)throw new Error(p.detail);await datasets();id('pa-dataset').value=p.id;id('pa-dataset').onchange();id('pa-message').textContent=`Validated ${p.rows} observations. ${p.quality.duplicates_removed} duplicates removed; ${p.quality.rejected_count} rejected.`;}catch(e){id('pa-message').textContent=e.message;}};
    async function loadActivity(automatic=false) {
      if(model.activityLoading) return;
      model.activityLoading=true;id('pa-message').textContent='Loading AIS positions…';id('pa-export').disabled=true;
      try {
        let input=activityRequest(),p;
        for(let attempt=0;attempt<4;attempt++) {
          try {p=await api('/api/port-activity/analyze',input);break;}
          catch(e) {
            if(!automatic || !e.message.includes('100,000-row') || attempt===3) throw e;
            const end=new Date(input.end),start=new Date(input.start);
            id('pa-start').value=new Date(end.getTime()-(end-start)/2).toISOString().slice(0,16);
            input=activityRequest();
          }
        }
        model.activityInput={...input,snapshot_id:p.snapshot_id};model.activity=p;renderActivity(p);
        id('pa-message').textContent=`${p.positions.length} vessels shown from ${input.start || p.source.first_observation} to ${input.end || p.source.last_observation}. Historical AIS observations; timestamps and age are shown on each vessel.`;
      } catch(e) {id('pa-message').textContent=e.message;}
      finally {model.activityLoading=false;}
    }
    id('pa-form').onsubmit=e=>{e.preventDefault();return loadActivity();};
    id('pa-export').onclick=async()=>{try{download(await api('/api/port-activity/export',model.activityInput,true),'ais-visit-audit.csv');}catch(e){id('pa-message').textContent=e.message;}};
    if(available.live.rows>0) {id('pa-dataset').value='live';id('pa-dataset').onchange();await loadActivity(true);}
  }
  window.openAnalystWorkspace=mode=>(mode==='voyage-analysis'?initVoyage():initActivity()).catch(e=>{const surface=id(mode+'-surface');const p=document.createElement('p');p.textContent=e.message;surface.append(p);});
  window.AnalystHelpers={endpoint,routeLines,chart};
})();
