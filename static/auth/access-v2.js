"use strict";
(() => {
  const originalFetch=window.fetch.bind(window), $=id=>document.getElementById(id);
  const modes={'voyage-analysis':'voyage_analysis','port-activity':'port_activity',energy:'energy',ports:'ports',coal:'india_coal',commodities:'commodities',news:'news',weather:'weather',rivers:'rivers'};
  let user;
  window.hrpCan=(section,edit=false)=>!user?.enabled || (edit?user.permissions?.[section]==='edit':['view','edit'].includes(user.permissions?.[section]));
  window.hrpModeAllowed=mode=>window.hrpCan(modes[mode]);
  window.hrpAuthReady=originalFetch('/api/auth/me',{cache:'no-store'}).then(async response=>{
    if(!response.ok){window.location.assign('/auth/login');return null;}
    user=await response.json();window.hrpAccess=user;
    if(user.enabled){window.sessionStorage?.removeItem('hrpAdminToken');if(!user.authenticated){window.location.assign('/auth/status');return null;}}
    return user;
  });
  const trackers={coal_plants:'energy',solar:'energy',wind:'energy',hydro:'energy',nuclear:'energy',geothermal:'energy',bioenergy:'energy',world_ports:'ports',coal_mines:'commodities',coal_terminals:'commodities',coal_trade_terminals:'commodities',iron_ore_mines:'commodities',iron_ore_terminals:'commodities',steel_plants:'commodities',cement_plants:'commodities'};
  const prefixes={'/api/voyage/':'voyage_analysis','/api/port-activity/':'port_activity','/api/ports':'ports','/api/coal/':'india_coal','/api/npp/':'india_coal','/api/india/sources':'india_coal','/api/news':'news','/api/ais/':'live_ais','/api/vessel/':'live_ais','/api/river-levels':'rivers','/api/weather':'weather','/api/imd/':'weather','/api/bmkg/':'weather','/api/sea/':'weather','/api/coastal-weather/':'weather','/api/major-port-weather':'weather','/api/port-disruptions':'weather','/api/port-disruption-outlook':'weather','/api/route':'voyage_distance','/api/routing/':'voyage_distance','/api/zones':'voyage_distance','/api/bunker':'voyage_distance'};
  function sections(url) {
    const match=url.pathname.match(/^\/api\/(?:map|data|kpis|countries|export)\/([^/]+)$/);
    if(match)return [trackers[match[1]]];
    if(url.pathname==='/api/layer-facets')return (url.searchParams.get('trackers')||'').split(',').map(id=>trackers[id]);
    for(const [prefix,key] of Object.entries(prefixes))if(url.pathname===prefix.replace(/\/$/,'')||url.pathname.startsWith(prefix.endsWith('/')?prefix:prefix+'/'))return [key];
    return [];
  }
  window.fetch=async(input,init={})=>{
    const url=new URL(typeof input==='string'?input:input.url,window.location.href);
    if(url.origin!==window.location.origin)return originalFetch(input,init);
    await window.hrpAuthReady;
    if(user?.enabled && sections(url).some(section=>!window.hrpCan(section))) {
      return new Response(JSON.stringify({detail:'This section is hidden for your account.'}),{status:403,headers:{'Content-Type':'application/json'}});
    }
    const options={...init}, method=String(init.method || (typeof input==='string'?'GET':input.method)||'GET').toUpperCase();
    if(user?.enabled && (!['GET','HEAD','OPTIONS'].includes(method)||['true','1','yes'].includes(url.searchParams.get('force')))) {
      options.headers=new Headers(init.headers || (typeof input!=='string'?input.headers:undefined));options.headers.set('X-CSRF-Token',user.csrf);
    }
    const response=await originalFetch(input,options);
    if(user?.enabled && response.status===401)window.location.assign('/auth/login');
    return response;
  };
  function controls() {
    if(!user?.enabled)return;
    document.querySelectorAll('details[data-mode]').forEach(node=>{node.hidden=!window.hrpModeAllowed(node.dataset.mode);});
    document.querySelector('.ais-section').hidden=!window.hrpCan('live_ais');
    document.querySelector('.voyage-section').hidden=!window.hrpCan('voyage_distance');
    const edits={'#coal-upload,#coal-upload-input,#coal-analysis-refresh,#npp-refresh':'india_coal','#news-refresh,[data-review]':'news','#coastal-weather-refresh':'weather','#river-level-refresh':'rivers','#pa-upload':'port_activity'};
    for(const [selector,section] of Object.entries(edits))document.querySelectorAll(selector).forEach(node=>{node.hidden=!window.hrpCan(section,true);});
    document.querySelectorAll('[data-admin-only]').forEach(node=>{node.hidden=user.role!=='admin';});
  }
  document.addEventListener('DOMContentLoaded',async()=>{
    await window.hrpAuthReady;if(!user?.enabled)return;
    $('account-controls').hidden=false;$('account-label').textContent=`${user.email} · ${user.role==='admin'?(user.sso?'HRP administrator':'Owner'):'Approved colleague'}`;
    $('access-open').hidden=user.role!=='admin'||user.sso;$('access-open').textContent='Access requests';
    if(!user.sso)$('access-open').onclick=()=>window.location.assign('/auth/access-requests');
    $('account-logout').onclick=async()=>{await window.fetch('/auth/logout',{method:'POST'});window.location.assign('/');};
    controls();new MutationObserver(controls).observe(document.body,{childList:true,subtree:true});
  });
})();
