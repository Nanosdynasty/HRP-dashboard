const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = vm.createContext({ window: { fetch: async () => {} }, document: { addEventListener() {} } });
vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/js/app.js'), 'utf8'), context);
const rain = row => context.hasRainSignal(row);

test('negative conditions and generic descriptions do not produce rain symbols', () => {
  assert.equal(rain({ weather_condition: 'No Rain' }), false);
  assert.equal(rain({ rainfall_category: 'No rain' }), false);
  assert.equal(rain({ weather_condition: 'Fair', weather_description: 'Rain symbols in legend' }), false);
  assert.equal(rain({ rainfall_category: 'Nil' }), false);
  assert.equal(rain({ weather_condition: 'Tidak hujan' }), false);
  assert.equal(rain({ weather_condition: 'Thundershowers' }), true);
  assert.equal(rain({ weather_condition: 'Hujan ringan' }), true);
  assert.equal(rain({ rainfall_category: 'Heavy' }), true);
});

test('expired and stale forecasts cannot create animated weather symbols', () => {
  for (const row of [{freshness_status:'stale'}, {forecast_expired:true}, {valid_to:'2000-01-01T00:00:00Z'}]) {
    assert.equal(context.weatherForecastExpired(row), true);
    assert.equal(context.weatherDominantSignal({...row, weather_condition:'Rain'}), null);
  }
});

test('a current cyclone without a published forecast expiry displays a storm symbol', () => {
 const row={location_type:'storm',location_name:'SURIGAE',storm_active:true,valid_to:null,forecast_expired:false,freshness_status:'current',alert_level:'Orange'};
 assert.equal(context.weatherForecastExpired(row),false);
 assert.equal(context.weatherDominantSignal(row).kind,'cyclone');
 assert.equal(context.weatherDominantSignal({...row,freshness_status:'stale'}),null);
});
