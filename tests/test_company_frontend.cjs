const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
function setup(permissions={ports:'view',voyage_distance:'view'},authenticated=true){
  const calls=[], redirects=[];
  const window={location:{href:'https://dashboard.example/',origin:'https://dashboard.example',assign:url=>redirects.push(url)},sessionStorage:{removeItem(){}}};
  window.fetch=async(input,init={})=>{calls.push({input,init});return {ok:true,status:200,json:async()=>({enabled:true,authenticated,status:'approved',permissions,csrf:'test-csrf'})};};
  vm.runInNewContext(fs.readFileSync('static/auth/access-v2.js','utf8'),{window,document:{addEventListener(){}},URL,Headers,Response,console});
  return {window,calls,redirects};
}
test('hidden data is not fetched, including tracker APIs and mixed facets',async()=>{
  const {window,calls}=setup();await window.hrpAuthReady;
  for(const path of ['/api/coal/dashboard','/api/map/solar','/api/export/coal_mines','/api/layer-facets?trackers=world_ports,coal_mines']){
    const count=calls.length;assert.equal((await window.fetch(path)).status,403);assert.equal(calls.length,count);
  }
  assert.equal((await window.fetch('/api/ports')).status,200);
});
test('CSRF is applied to permitted writes and forced refresh, never external requests',async()=>{
  const {window,calls}=setup({voyage_distance:'view',india_coal:'edit'});await window.hrpAuthReady;
  await window.fetch('/api/route',{method:'POST',body:'{}'});assert.equal(calls.at(-1).init.headers.get('X-CSRF-Token'),'test-csrf');
  await window.fetch('/api/npp/power-dashboard?force=true');assert.equal(calls.at(-1).init.headers.get('X-CSRF-Token'),'test-csrf');
  await window.fetch('https://external.example/data',{method:'POST'});assert.equal(calls.at(-1).init.headers,undefined);
  assert.equal(window.hrpCan('india_coal',true),true);assert.equal(window.hrpCan('voyage_distance',true),false);
});
test('Microsoft-only identity is sent to setup, never treated as a dashboard session',async()=>{
  const {window,redirects}=setup({},false);await window.hrpAuthReady;
  assert.deepEqual(redirects,['/auth/status']);
});
test('startup waits for identity and loads only authorized sections',()=>{
  const code=fs.readFileSync('static/js/app.js','utf8');
  const init=code.slice(code.indexOf('async function init()'),code.indexOf('async function loadRiskZones()'));
  assert.ok(init.indexOf('await window.hrpAuthReady')<init.indexOf('loadCoalWorkspace()'));
  assert.match(init,/hrpCan\?\.\('india_coal'\) \? loadCoalWorkspace/);
  assert.match(init,/hrpCan\?\.\('voyage_distance'\)/);
});
