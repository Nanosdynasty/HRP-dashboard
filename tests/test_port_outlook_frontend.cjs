const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function harness() {
  const nodes = new Map(); const markers = []; const requests = [];
  const get = id => {
    if (!nodes.has(id)) nodes.set(id, {innerHTML:'',textContent:'',dataset:{},hidden:false,addEventListener(){},scrollIntoView(){}});
    return nodes.get(id);
  };
  const layer = {addTo(){return this;},clearLayers(){markers.length=0;}};
  const map = {setView(){return this;},invalidateSize(){}};
  const context = vm.createContext({URL,URLSearchParams,Blob,FormData:class { *[Symbol.iterator](){yield ['port','1'];}},setTimeout:fn=>fn(),console,
    document:{getElementById:get,querySelectorAll:()=>[],createElement:()=>({click(){}})},
    L:{map:()=>map,tileLayer:()=>({addTo(){}}),layerGroup:()=>layer,circleMarker:(point, options)=>{markers.push({point,options});return {bindTooltip(){return this;},on(){return this;},addTo(){return this;}};}},
    escapeHtml:v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),escapeAttr:v=>String(v??'').replaceAll('"','&quot;'),
    fetch:async url=>{requests.push(url);return {ok:false,status:503};},showPortCard(){}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../static/js/port-outlook.js'),'utf8'), context);
  return {context,get,markers,requests};
}
function row(id='1',assessment='Weather watch') {
  return {row_id:id+':port:handling:0-24',port_id:id,port_name:'Test Port',country:'AU',country_name:'Australia',latitude:-20,longitude:118,scope_name:'Port area',scope_type:'port',operation:'loading/discharge',operation_group:'Cargo handling',forecast_window:'0-24',assessment,actual_operating_status:'Not reported',weather_resolution:['marine-area forecast mapped to a port'],coverage_limitations:['Published limits unavailable'],role:'Loading',commodities:['Iron ore'],assessment_basis:['Rain forecast'],potential_windows:[],freshness:{},applicable_rules:[],provenance:[],notices:[],source_links:[]};
}
test('map groups the exact filtered rows and takes the highest priority scope',()=>{
  const h=harness(); h.context.fixture={rows:[row(),{...row('1','Confirmed restriction'),row_id:'notice'},row('2','Not assessed')],filtered_port_count:2,inventory_count:783,generated_at:'2026-09-28T06:00:00Z',unmatched_records:[],sources:[],source_errors:{},filters:{port:'1'},snapshot_id:'s1'};
  vm.runInContext('portOutlook.payload=fixture;renderPortOutlook()',h.context);
  assert.equal(h.markers.length,2);
  assert.equal(h.markers[0].options.color,'#b51f36');
  assert.match(h.get('outlook-table').innerHTML,/Not reported/);
  assert.match(h.get('outlook-status').textContent,/2 ports/);
  assert.match(h.get('outlook-pagination').innerHTML,/all 3 filtered rows/);
});
test('failure preserves the displayed snapshot and reports source error',async()=>{
  const h=harness(); h.context.fixture={rows:[row()]};
  vm.runInContext('portOutlook.payload=fixture',h.context);
  await h.context.loadPortOutlook();
  assert.match(h.get('outlook-status').textContent,/Last displayed snapshot retained/);
  assert.equal(vm.runInContext('portOutlook.payload.rows.length',h.context),1);
});
test('port detail escapes source text and shows forecast resolution and gaps',()=>{
  const h=harness();h.context.fixture={...row(),assessment_basis:['<script>bad</script>']};
  const html=vm.runInContext('outlookRowDetail(fixture)',h.context);
  assert.match(html,/&lt;script&gt;/);
  assert.match(html,/Published limits unavailable/);
  assert.match(html,/marine-area forecast/);
  assert.match(html,/Actual operating status/);
});
test('export reuses displayed filters and snapshot rather than unapplied form edits',async()=>{
  const h=harness();h.context.fixture={rows:[row()],filters:{port:'original',country:'AU',sort:'assessment',direction:'asc'},snapshot_id:'displayed-snapshot'};
  vm.runInContext('portOutlook.payload=fixture',h.context);
  await h.get('outlook-export').onclick();
  assert.match(h.requests[0],/port=original/);
  assert.match(h.requests[0],/snapshot_id=displayed-snapshot/);
  assert.match(h.get('outlook-status').textContent,/Export failed/);
});
