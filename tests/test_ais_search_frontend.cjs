const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/js/app.js'),'utf8');
test('search works while the AIS toggle is off and pins/locates an out-of-region vessel',async()=>{
 const functions=source.slice(source.indexOf('function displayedAisVessels()'),source.indexOf('function aisVesselTypeCategory'))+'\n'+source.slice(source.indexOf('async function refreshAisLayer('),source.indexOf('function aisObservationAgeClass'));
 const elements=new Map();const doc={getElementById:id=>{if(!elements.has(id))elements.set(id,{value:id==='ais-search'?'9000007':'',disabled:false,checked:false,textContent:''});return elements.get(id)}};
 let url,center,rendered,status;
 const vessel={mmsi:'900000001',imo:'9000007',lat:-35,lon:-70,ship_type:30,last_update:'2026-09-28T10:00:00Z'};
 const state={aisEnabled:false,aisLoading:false,mode:'ports',aisDisplayMode:'all',aisRegions:new Set(['india']),aisTypeFilter:'cargo',aisWatchlist:new Map(),aisVessels:[],aisLayer:{addTo(){}},map:{hasLayer:()=>false,setView:p=>center=p}};
 const ctx={state,document:doc,L:{},console,encodeURIComponent,Date,Number,Map,Array,aisVesselInSelectedRegions:()=>false,aisVesselTypeCategory:()=> 'fishing',currentAisBounds:()=>({}),setAisStatus:text=>status=text,
 addAisWatchlistVessels:rows=>rows.forEach(v=>state.aisWatchlist.set(v.mmsi,v)),renderAisVessels:()=>{rendered=ctx.displayedAisVessels().length},fetch:async u=>{url=u;return {ok:true,json:async()=>({vessels:[vessel]})}}};
 vm.createContext(ctx);vm.runInContext(functions,ctx);await ctx.refreshAisLayer(true);
 assert.equal(url,'/api/ais/search?q=9000007');assert.equal(rendered,1);assert.equal(JSON.stringify(center),'[-35,-70]');assert.ok(state.aisEnabled);assert.ok(status.includes('timestamp'));assert.ok(doc.getElementById('ais-enabled').checked);
});
