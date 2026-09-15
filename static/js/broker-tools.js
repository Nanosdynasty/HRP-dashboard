/* Broker-facing interpretation uses published fields; thresholds are screening aids. */
function brokerWeatherSummary(row) {
  const finite = value => value == null || value === '' ? null : Number.isFinite(Number(value)) ? Number(value) : null;
  const knots = finite(row.wind_speed_max_kn) ?? (finite(row.wind_speed_max_kmph) == null ? null : Number(row.wind_speed_max_kmph) / 1.852);
  const waves = finite(row.wave_height_max_m);
  const expired = row.freshness_status === 'stale' || (row.valid_to && Date.parse(row.valid_to) < Date.now());
  const items = [];
  if (hasRainSignal(row)) items.push('Rain forecast: check hatch and moisture-sensitive cargo handling arrangements.');
  if (knots != null && knots >= 22) items.push('Wind ≥22 kt: confirm crane, pilot and tug limits with the terminal or agent.');
  if (waves != null && waves >= 2.5) items.push('Waves ≥2.5 m: check approach, anchorage and pilot boarding conditions.');
  if (row.port_operational_status && !['Not reported', 'Unknown'].includes(row.port_operational_status)) items.unshift(`Reported port status: ${row.port_operational_status}.`);
  if (expired) items.unshift('Forecast has expired: obtain the latest bulletin before evaluating the call.');
  const adverse = weatherAdverseCondition(row);
  if (adverse) items.unshift(adverse);
  return {items, expired, knots, waves, label: expired ? 'Update needed' : adverse ? 'Adverse weather' : items.length ? 'Conditions to check' : 'Review forecast', tone: expired ? 'stale' : adverse ? 'adverse' : 'review'};
}

function brokerWeatherPanel(row) {
  if (row.location_type === 'storm') return brokerWeatherSummary(row).expired ? '<section class="broker-weather-panel stale"><strong>Expired advisory — not a current warning</strong><p>Obtain the latest official cyclone advisory before assessing port exposure.</p></section>' : '';
  const info = brokerWeatherSummary(row);
  const cell = (name, value) => `<div><span>${name}</span><strong>${escapeHtml(value)}</strong></div>`;
  return `<section class="broker-weather-panel ${info.tone}"><header><strong>${info.label}</strong><span>Call planning</span></header>
    <div class="broker-weather-values">${info.knots == null ? '' : cell('Maximum wind', `${info.knots.toFixed(0)} kt`)}${info.waves == null ? '' : cell('Maximum waves', `${info.waves.toFixed(1)} m`)}${row.weather_condition || row.rainfall_category ? cell('Conditions', row.weather_condition || row.rainfall_category) : ''}</div>
    ${info.items.length ? `<ul>${info.items.map(text => `<li>${escapeHtml(text)}</li>`).join('')}</ul>` : '<p>No handling trigger identified in the available fields. Operating status still needs agent confirmation.</p>'}
    <small>Weather screening, not a port restriction. Wind/wave triggers are indicative; vessel and terminal limits vary.</small></section>`;
}

function brokerWeatherTiming(row) {
  const date = value => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString('en-GB', {day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',timeZone:'UTC',hour12:false}) + ' UTC' : null;
  const issued=date(row.issued_at), end=date(row.valid_to);
  return `<div class="broker-weather-timing">${issued ? `<span>Issued <strong>${escapeHtml(issued)}</strong></span>` : '<span>Issue time not published</span>'}${end ? `<span>Valid until <strong>${escapeHtml(end)}</strong></span>` : '<span>Validity end not published</span>'}</div>`;
}

function brokerWeatherOverview(rows) {
  const ports=rows.filter(r=>r.location_type==='port');
  const adverse=rows.filter(r=>weatherAdverseCondition(r));
  const expired=state.coastalWeatherRows.filter(r=>brokerWeatherSummary(r).expired);
  const rain=ports.filter(r=>hasRainSignal(r));
  return `<section class="broker-weather-overview" aria-label="Filtered weather briefing"><div><span>Current port forecasts</span><strong>${ports.length}</strong></div><div><span>Current adverse-weather records</span><strong>${adverse.length}</strong></div><div><span>Current ports with rain forecast</span><strong>${rain.length}</strong></div><div><span>Expired records excluded</span><strong>${expired.length}</strong></div><p>Only current records appear below. Rain indicates a cargo-handling check—not a confirmed delay. Expired records are excluded from maps, cards and current exports.</p></section>`;
}

function brokerForecastTimeline(row) {
  const rows = state.coastalWeatherRows.filter(item => item.location_id === row.location_id && item.provider_code === row.provider_code)
    .filter(item => item.valid_from || item.valid_date).sort((a,b) => Date.parse(a.valid_from || a.valid_date) - Date.parse(b.valid_from || b.valid_date));
  const unique = [...new Map(rows.map(item => [item.valid_from || item.valid_date, item])).values()];
  if (unique.length < 2) return '<p class="broker-timeline-note">This source response contains one forecast period. Use the forecast-time selector for other available periods.</p>';
  return `<div class="broker-timeline" aria-label="Published forecast periods">${unique.slice(0,12).map(item => {
    const info = brokerWeatherSummary(item);
    return `<div><time>${escapeHtml(new Date(item.valid_from || item.valid_date).toLocaleString('en-GB',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}))}</time><strong>${info.knots == null ? '—' : info.knots.toFixed(0) + ' kt'}</strong><span>${info.waves == null ? '—' : info.waves.toFixed(1) + ' m'}</span><small>${escapeHtml(item.weather_condition || '')}</small></div>`;
  }).join('')}</div>`;
}

const BROKER_CHART_TYPES = ['line','area','column','bar','stacked','percent','step','scatter','lollipop','heatmap','pie','donut'];
const brokerChartChoices = new Map();
function renderBrokerChart(id, rows, chart) {
  const target = document.getElementById(id);
  if (!target || !rows.length || !(chart.series || []).length) return false;
  const key = chart.id || chart.title || id;
  const mode = brokerChartChoices.get(key) || (chart.type === 'stacked_column' ? 'stacked' : chart.type === 'column' ? 'column' : 'line');
  target.innerHTML = `<div class="broker-chart-controls"><label>Chart <select aria-label="Chart type for ${escapeAttr(chart.title || '')}">${BROKER_CHART_TYPES.map(type => `<option value="${type}" ${type===mode?'selected':''}>${({percent:'100% stacked',scatter:'Scatter by period',pie:'Pie · period totals',donut:'Donut · period totals'})[type] || labelize(type)}</option>`).join('')}</select></label><button type="button">Download plotted CSV</button></div><div class="broker-chart-body"></div>`;
  target.querySelector('select').onchange = event => {brokerChartChoices.set(key,event.target.value);renderBrokerChart(id,rows,chart);};
  target.querySelector('button').onclick = () => {
    const fields = ['period', ...chart.series.map(s=>s.key)];
    const csv = [fields,...rows.map(r=>fields.map(f=>r[f] ?? ''))].map(r=>r.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\r\n');
    const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='filtered-chart.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  const series=chart.series, colors=['#125780','#2b98a1','#c77c32','#795bb1','#c34450','#71953e'];
  const num=v=>v==null||v===''?null:Number.isFinite(Number(v))?Number(v):null;
  const matrix=rows.map(r=>series.map(s=>num(r[s.key])));
  const values=matrix.flat().filter(v=>v!=null);
  const body=target.querySelector('.broker-chart-body');
  if (!values.length){body.textContent='No verified numeric observations for this selection.';return true;}
  const W=800,H=340,L=76,R=22,T=22,B=62,pw=W-L-R,ph=H-T-B;
  const stack=mode==='stacked'||mode==='percent';
  const composition=stack||mode==='pie'||mode==='donut';
  if(composition && (series.length<2 || series.some(s=>/pct|percent|share|ytd|ratio|index/i.test(s.key)) || /%|ratio|index/i.test(chart.y_label||''))){body.textContent='Composition requires at least two additive quantity series. Use line, column or heatmap for percentages, indices or cumulative values.';return true;}
  if(composition && matrix.some(r=>r.some(v=>v==null))){body.textContent='Some series have missing observations in this selection. Composition is unavailable to avoid an incomplete denominator; select a line or column chart to inspect the gaps.';return true;}
  if ((stack||mode==='pie'||mode==='donut') && values.some(v=>v<0)){body.textContent='This chart requires non-negative quantities. Select a line, column or scatter chart for signed changes.';return true;}
  const lo=Math.min(0,...values),hi=mode==='percent'?100:Math.max(1,...(stack?matrix.map(r=>r.reduce((s,v)=>s+(v||0),0)):values));
  const x=i=>L+(i+.5)*pw/rows.length,y=v=>T+ph-(v-lo)/(hi-lo)*ph;
  let marks='';
  const title=(i,j,v)=>`<title>${escapeHtml(formatMonthYear(rows[i].period))} · ${escapeHtml(series[j].label || series[j].key)}: ${v==null?'Missing':escapeHtml(formatNumber(v,2))} ${escapeHtml(chart.y_label || '')}</title>`;
  if(mode==='pie'||mode==='donut') {
    const totals=series.map((s,j)=>matrix.reduce((sum,r)=>sum+(r[j]||0),0)),total=totals.reduce((a,b)=>a+b,0);let angle=-Math.PI/2;
    if(!total){body.textContent='No positive quantities for composition.';return true;}
    totals.forEach((v,j)=>{const end=angle+2*Math.PI*v/total,c=colors[j%colors.length];if(v===total)marks+=`<circle cx="400" cy="155" r="116" fill="${c}"><title>${escapeHtml(series[j].label)}: ${formatNumber(v,2)}</title></circle>`;else if(v>0)marks+=`<path d="M400 155 L${400+116*Math.cos(angle)} ${155+116*Math.sin(angle)} A116 116 0 ${end-angle>Math.PI?1:0} 1 ${400+116*Math.cos(end)} ${155+116*Math.sin(end)} Z" fill="${c}"><title>${escapeHtml(series[j].label)}: ${formatNumber(v,2)} · ${(100*v/total).toFixed(1)}%</title></path>`;angle=end;});
    if(mode==='donut')marks+='<circle cx="400" cy="155" r="64" fill="white"/>';
    marks+='<text x="400" y="307" text-anchor="middle">Sum across selected periods · quantities only</text>';
  } else if(mode==='heatmap') {
    matrix.forEach((r,i)=>r.forEach((v,j)=>{marks+=`<rect x="${L+i*pw/rows.length}" y="${T+j*ph/series.length}" width="${pw/rows.length}" height="${ph/series.length}" fill="${v==null?'#e8edf0':colors[j%colors.length]}" opacity="${v==null?1:.15+.85*(v-lo)/(hi-lo)}">${title(i,j,v)}</rect>`;}));
    marks+=`<text x="${L}" y="${H-28}">Columns: reporting period · rows: series in legend order · grey: missing</text>`;
  } else if(mode==='bar') {
    const step=ph/rows.length;
    matrix.forEach((r,i)=>r.forEach((v,j)=>{if(v==null)return;const zero=L+(0-lo)/(hi-lo)*pw,end=L+(v-lo)/(hi-lo)*pw;marks+=`<rect x="${Math.min(zero,end)}" y="${T+i*step+j*step/series.length}" width="${Math.abs(end-zero)}" height="${Math.max(.5,step/series.length-1)}" fill="${colors[j%colors.length]}">${title(i,j,v)}</rect>`;}));
    rows.forEach((r,i)=>{if(i%Math.max(1,Math.ceil(rows.length/8))===0)marks+=`<text x="${L-7}" y="${T+(i+.5)*step}" text-anchor="end">${escapeHtml(formatMonthYear(r.period))}</text>`;});
    marks+=`<text x="400" y="${H-20}" text-anchor="middle">${escapeHtml(chart.y_label)} · hover bars for exact values</text>`;
  } else {
    for(let k=0;k<=4;k++){const v=lo+(hi-lo)*k/4;marks+=`<line x1="${L}" y1="${y(v)}" x2="${W-R}" y2="${y(v)}" stroke="#e3eaf0"/><text x="${L-9}" y="${y(v)+4}" text-anchor="end">${formatNumber(v,0)}${mode==='percent'?'%':''}</text>`;}
    series.forEach((s,j)=>{const c=colors[j%colors.length];let path='';matrix.forEach((r,i)=>{const v=r[j];if(v==null){path='';return;}let baseline=0,top=v;if(stack){baseline=r.slice(0,j).reduce((a,b)=>a+(b||0),0);if(mode==='percent'){const total=r.reduce((a,b)=>a+(b||0),0);if(!total)return;baseline=baseline/total*100;top=v/total*100;}top+=baseline;}
      if(['column','stacked','percent'].includes(mode)){const width=pw/rows.length*.82/(stack?1:series.length);marks+=`<rect x="${x(i)-pw/rows.length*.41+(stack?0:j*width)}" y="${Math.min(y(top),y(baseline))}" width="${width}" height="${Math.abs(y(top)-y(baseline))}" fill="${c}">${title(i,j,v)}</rect>`;}
      else {if(mode==='lollipop')marks+=`<line x1="${x(i)}" y1="${y(0)}" x2="${x(i)}" y2="${y(v)}" stroke="${c}"/>`;if(!['scatter','lollipop'].includes(mode)&&path){marks+=`<path d="M${path} ${mode==='step'?`H${x(i)} V${y(v)}`:`L${x(i)} ${y(v)}`}" fill="none" stroke="${c}" stroke-width="2"/>`;}
      if(mode==='area')marks+=`<rect x="${x(i)-pw/rows.length/2}" y="${Math.min(y(v),y(0))}" width="${pw/rows.length}" height="${Math.abs(y(0)-y(v))}" fill="${c}" opacity=".12"/>`;
      marks+=`<circle cx="${x(i)}" cy="${y(v)}" r="3" fill="${c}">${title(i,j,v)}</circle>`;path=`${x(i)} ${y(v)}`;}
    });});
    const ticks=new Set(Array.from({length:Math.min(7,rows.length)},(_,i)=>Math.round(i*(rows.length-1)/Math.max(1,Math.min(7,rows.length)-1))));
    rows.forEach((r,i)=>{if(ticks.has(i))marks+=`<text x="${x(i)}" y="${H-34}" text-anchor="middle">${escapeHtml(formatMonthYear(r.period))}</text>`;});
    marks+=`<text x="400" y="${H-9}" text-anchor="middle">Reporting period</text><text transform="translate(15 150) rotate(-90)" text-anchor="middle">${escapeHtml(mode==='percent'?'Share of reported series (%)':chart.y_label)}</text>`;
  }
  body.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${escapeAttr(chart.title)}">${marks}</svg><div class="broker-chart-legend">${series.map((s,j)=>`<span><i style="background:${colors[j%colors.length]}"></i>${escapeHtml(s.label||s.key)}</span>`).join('')}</div>`;
  return true;
}
