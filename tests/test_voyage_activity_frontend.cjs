const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');const path=require('node:path');
const root=path.join(__dirname,'..');const source=fs.readFileSync(path.join(root,'static/js/voyage-activity.js'),'utf8');
function helpers(){const window={};vm.runInNewContext(source,{window,document:{getElementById:()=>null},fetch:()=>{},setTimeout:()=>{},console,URL,FormData,Date});return window.AnalystHelpers;}
test('coordinates use longitude then latitude and ambiguous names are rejected',()=>{const h=helpers();const p=h.endpoint('118.5,-20.3');assert.equal(p.lon,118.5);assert.equal(p.lat,-20.3);assert.throws(()=>h.endpoint('Newcastle'));assert.throws(()=>h.endpoint(',20'));});
test('map line chunks never draw across the dateline',()=>{const lines=helpers().routeLines([[170,0],[179,1],[-179,2],[-170,3]]);assert.equal(lines.length,2);for(const line of lines)for(let i=1;i<line.length;i++)assert.ok(Math.abs(line[i][0]-line[i-1][0])<=180);});
test('bars escape labels and missing estimates stay unavailable',()=>{const html=helpers().chart([{name:'<script>',hours:null}],'name','hours','Waiting hours');assert.ok(html.includes('&lt;script&gt;'));assert.ok(html.includes('Not assessed'));});
test('sidebar, styles and workspace lifecycle are wired into existing shell',()=>{const html=fs.readFileSync(path.join(root,'static/index.html'),'utf8');const app=fs.readFileSync(path.join(root,'static/js/app.js'),'utf8');for(const name of ['voyage-analysis','port-activity']){assert.ok(html.includes(`data-mode="${name}"`));assert.ok(html.includes(`id="${name}-surface"`));assert.ok(app.includes(`mode !== "${name}"`));}assert.ok(html.includes('/static/js/voyage-activity.js'));assert.ok(html.includes('/static/css/voyage-activity.css'));assert.ok(app.includes('window.openAnalystWorkspace?.(mode)'));});
test('AIS export uses displayed snapshot, and synthetic sample is explicit',()=>{assert.ok(source.includes('snapshot_id:p.snapshot_id'));assert.ok(source.includes('model.activityInput,true'));assert.ok(source.includes('synthetic test sample'));assert.ok(source.includes('not real vessel observations'));});
test('workspaces initialize forms and catalogue presets without external providers',async()=>{
  const nodes=new Map();
  function node(name){if(!nodes.has(name)){const n={value:'',textContent:'',disabled:false,addEventListener(){},append(){}};Object.defineProperty(n,'innerHTML',{get(){return this.html||''},set(html){this.html=html;for(const m of html.matchAll(/id="([^"]+)"/g))node(m[1]);}});nodes.set(name,n);}return nodes.get(name);}
  node('voyage-analysis-surface');node('port-activity-surface');
  const window={}; const mapObject={setView(){return this},invalidateSize(){},fitBounds(){}};const layer={addTo(){return this},clearLayers(){}};
  let markers=0,analysisCalls=0;
  const marker={bindPopup(){return this},addTo(){return this}};
  const L={map:()=>mapObject,layerGroup:()=>layer,tileLayer:()=>layer,latLngBounds:p=>p,circleMarker:()=>{markers++;return marker}};
  const ports=[{port_id:'za',name:'RICHARDS BAY',country:'South Africa',country_code:'ZA'},{port_id:'in',name:'PARADIP',country:'India',country_code:'IN'},{port_id:'au',name:'PORT HEDLAND',country:'Australia',country_code:'AU'},{port_id:'cn',name:'QINGDAO GANG',country:'China',country_code:'CN'}];
  const fetch=async url=>{
    if(url.includes('/analyze')) {analysisCalls++;if(analysisCalls===1)return {ok:false,text:async()=>JSON.stringify({detail:'Live history exceeds 100,000-row analysis bound'})};}
    return {ok:true,json:async()=>{
    if(url.includes('/analyze')) {return {positions:[{mmsi:'900000001',lat:20,lon:80,timestamp:'2026-09-28T09:57:53Z',age_hours:0,status:'outside'}],trajectories:[],events:[],stops:[],weekly:[],rules:{},quality:{gaps:0,aggregate_congestion_available:false},source:{source:'Collected history',coverage:'Partial receivers',first_observation:'2026-09-28T09:00:00Z',last_observation:'2026-09-28T09:57:53Z'},snapshot_id:'test'};}
    return url.includes('/voyage/ports')?{rows:ports}:url.includes('/market-context')?{rows:[],limitation:'country context',period:'2024-25'}:{rows:[],live:{rows:10,coverage:'Partial receivers',last_observation:'2026-09-28T09:57:53Z'},gaps:['DWT unavailable']};
  }};};
  vm.runInNewContext(source,{window,document:{getElementById:name=>nodes.get(name)||null,createElement:()=>({})},fetch,L,setTimeout:fn=>fn(),console,URL,Date,FormData});
  await window.openAnalystWorkspace('voyage-analysis');
  assert.ok(node('va-origins').value.includes('RICHARDS BAY'));assert.ok(node('va-destination').value.includes('PARADIP'));
  node('va-ore').onclick();assert.ok(node('va-destination').value.includes('QINGDAO GANG'));assert.equal(node('va-tonnes').value,180000);
  await window.openAnalystWorkspace('port-activity');assert.equal(node('pa-zones').value,'');
  assert.equal(node('pa-dataset').value,'live');assert.equal(analysisCalls,2);assert.equal(markers,1);assert.ok(node('pa-message').textContent.includes('1 vessels shown'));
  node('pa-dataset').value='live';node('pa-dataset').onchange();assert.ok(node('pa-start').value.startsWith('2026-09-28'));
  node('pa-dataset').value='uploaded';node('pa-dataset').onchange();assert.equal(node('pa-start').value,'');assert.equal(node('pa-end').value,'');
});
