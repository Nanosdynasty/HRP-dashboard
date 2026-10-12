const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup(role='viewer') {
  const calls=[], redirects=[];
  const window={location:{href:'https://dashboard.example/',origin:'https://dashboard.example',assign:url=>redirects.push(url)}};
  window.fetch=async(input,init={})=>{
    calls.push({input,init});
    return {ok:true,status:200,json:async()=>({enabled:true,status:'approved',role,email:'viewer@example.com',csrf:'session-csrf'})};
  };
  const context={window,document:{addEventListener(){}},URL,Headers,console};
  vm.runInNewContext(fs.readFileSync('static/auth/access.js','utf8'),context);
  return {window,calls,redirects};
}

test('CSRF attaches to same-origin writes and forced refresh, never an external URL',async()=>{
  const {window,calls}=setup(); await window.hrpAuthReady;
  await window.fetch('/api/route',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  assert.equal(calls.at(-1).init.headers.get('X-CSRF-Token'),'session-csrf');
  await window.fetch('/api/npp/power-dashboard?force=true');
  assert.equal(calls.at(-1).init.headers.get('X-CSRF-Token'),'session-csrf');
  await window.fetch('https://external.example/data',{method:'POST'});
  assert.equal(calls.at(-1).init.headers,undefined);
  await window.fetch('/api/ports');
  assert.equal(calls.at(-1).init.headers,undefined);
});

test('account role is loaded before requests and does not expose an admin token',async()=>{
  const {window,calls}=setup();
  await window.fetch('/api/route',{method:'POST'});
  assert.equal(window.hrpAccess.role,'viewer');
  assert.equal(calls[0].input,'/api/auth/me');
  assert.equal(calls.at(-1).init.headers.get('X-Admin-Token'),null);
});
