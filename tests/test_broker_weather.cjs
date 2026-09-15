const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context=vm.createContext({Date,Map,Number,hasRainSignal:r=>r.weather_condition==='Rain',weatherAdverseCondition:r=>r.adverse||'',escapeHtml:s=>String(s),state:{coastalWeatherRows:[]}});
vm.runInContext(fs.readFileSync('static/js/broker-tools.js','utf8'),context);
test('wind converted to knots and missing values remain missing',()=>{
  assert.equal(context.brokerWeatherSummary({wind_speed_max_kmph:18.52}).knots,10);
  assert.equal(context.brokerWeatherSummary({}).knots,null);
  assert.equal(context.brokerWeatherSummary({wind_speed_max_kn:0}).knots,0);
});
test('expired forecast leads the briefing',()=>{
  const result=context.brokerWeatherSummary({valid_to:'2000-01-01T00:00:00Z',weather_condition:'Rain'});
  assert.equal(result.label,'Update needed');
  assert.match(result.items[0],/expired/);
});
test('no invented missing metric tiles',()=>{
  const result=context.brokerWeatherPanel({});
  assert.ok(!result.includes('Maximum wind'));
  assert.ok(!result.includes('Maximum waves'));
  assert.match(result,/agent confirmation/);
});
