const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 const fields=['country','port','vessel','publisher','language','commodity_group','days'];const nodes={};
 const element=id=>nodes[id]||(nodes[id]={value:'',innerHTML:'',textContent:'',hidden:true,href:'',addEventListener(){},elements:Object.fromEntries(fields.map(k=>[k,{value:k==='commodity_group'?'all':'',options:[]}]))});
 let fail=false;
 const rows=Array.from({length:25},(_,i)=>({id:`a${i}`,title:`Article ${i}`,description:'<script>bad()</script>',link:'https://publisher.example/'+i,source_name:'Publisher',published_at:'2026-09-28',topics:['cargo_trade']}));
 const payload={rows,total:61,page:1,pages:3,page_size:25,archive_total:100,snapshot_id:'displayed-snapshot',facets:{},providers:[],event_count:61,coverage_note:'Collected coverage only'};
 const context=vm.createContext({window:{},document:{getElementById:element,querySelectorAll:()=>[],addEventListener(){}},state:{newsTopic:'all'},escapeHtml:v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),newsPublishedLabel:()=> 'Published today',URLSearchParams,FormData:class extends Array{constructor(){super(['days','7'],['page_size','25']);}},localStorage:{getItem:()=>null,setItem(){}},fetch:async()=>{if(fail)throw new Error('offline');return {ok:true,json:async()=>payload};},setInterval(){},clearTimeout(){},setTimeout(){}});
 vm.runInContext(fs.readFileSync('static/js/intelligence-desk.js','utf8'),context);
 return {context,nodes,payload,fail:()=>{fail=true;}};
}
test('all 25 page rows render and the exact displayed snapshot is exported',async()=>{
 const c=setup();await c.context.window.loadNews();assert.equal((c.nodes['news-feed'].innerHTML.match(/class="intelligence-article"/g)||[]).length,25);assert.ok(c.nodes['news-feed'].innerHTML.includes('Page 1 of 3'));assert.ok(c.nodes['intelligence-export'].href.includes('displayed-snapshot'));assert.ok(!c.nodes['news-feed'].innerHTML.includes('<script>bad()'));
});
test('a failed reload preserves the displayed collection and explains failure',async()=>{
 const c=setup();await c.context.window.loadNews();const before=c.nodes['news-feed'].innerHTML;c.fail();await c.context.window.loadNews();assert.equal(c.nodes['news-feed'].innerHTML,before);assert.match(c.nodes['intelligence-status'].textContent,/Previous results remain/);
});
