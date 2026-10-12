const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
const values={'river-waterway-filter':'','river-country-filter':'','river-type-filter':'','river-status-filter':''};
const context=vm.createContext({window:{fetch:async()=>{}},document:{addEventListener(){},getElementById(id){return {value:values[id]||''};}}});
vm.runInContext(fs.readFileSync('static/js/app.js','utf8'),context);
vm.runInContext(`state.mode='rivers';state.riverRows=[{country:'Indonesia',waterbody:'Musi River',latitude:-3.34,longitude:104.78},{country:'Panama',waterbody:'Panama Canal',latitude:9.12,longitude:-79.75}];state.map={fitBounds(points,options){window.captured={points,options};}};`,context);
test('river view fits Indonesian and Panama gauges rather than the old Atlantic bounds',()=>{
 context.focusRiverRows();assert.equal(context.window.captured.points.length,2);assert.equal(context.window.captured.points[0][1],104.78);
 values['river-country-filter']='Indonesia';context.focusRiverRows();assert.equal(context.window.captured.points.length,1);assert.equal(context.window.captured.points[0][0],-3.34);
 values['river-country-filter']='Panama';context.focusRiverRows();assert.equal(context.window.captured.points[0][1],-79.75);
});

test('Panama displays a named linked lake indicator without inventing a canal gauge level',()=>{
 const row={waterbody_type:'canal',level:null,extra_metrics:{'Gatún lake level':'84.7 ft'}};
 assert.equal(context.riverPrimaryValue(row),'84.7 ft (Gatún lake indicator)');
 assert.equal(context.riverPrimaryValue({level:null,waterbody_type:'river'}),'Not reported');
});
