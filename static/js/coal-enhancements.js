/* User-controlled card sizing and chart style choices for the Coal workspace. */
(() => {
  const styles = new Map(), last = new Map();
  const original = window.renderDynamicCoalChart;
  if (typeof original === 'function') window.renderDynamicCoalChart = (id, rows, chart) => { const next={...chart,type:styles.get(chart.id)||chart.type||'line'}; last.set(id,{rows,chart:next}); original(id,rows,next); if(next.type==='area'){const svg=document.querySelector('#'+id+' svg');if(svg){svg.querySelectorAll('polyline').forEach(line=>{const pts=(line.getAttribute('points')||'').trim();if(!pts)return;const p=pts.split(' ').map(x=>x.split(',').map(Number));const base=(svg.viewBox.baseVal.height||260)-43;const poly=document.createElementNS('http://www.w3.org/2000/svg','polygon');poly.setAttribute('points',[`${p[0][0]},${base}`,...p.map(x=>x.join(',')),`${p[p.length-1][0]},${base}`].join(' '));poly.setAttribute('fill',line.getAttribute('stroke')||'#163e72');poly.setAttribute('fill-opacity','.16');line.parentNode.insertBefore(poly,line);});}} };
  const enhance = () => document.querySelectorAll('#coal-dashboard-panels .cwx-card').forEach(card => {
    if (card.querySelector('.cwx-chart-style')) return;
    const chart=card.querySelector('.cwx-chart'), tools=card.querySelector('.cwx-card-tools')||card.querySelector('header'); if(!chart||!tools)return;
    const label=document.createElement('label'); label.className='cwx-chart-style'; label.textContent='Chart ';
    const select=document.createElement('select'); select.setAttribute('aria-label','Chart style');
    [['line','Line'],['area','Area'],['column','Columns'],['stacked_column','Stacked columns']].forEach(([v,t])=>{const o=document.createElement('option');o.value=v;o.textContent=t;select.append(o)});
    select.value=styles.get(card.dataset.chartId)||last.get(chart.id)?.chart.type||'line';
    select.onchange=()=>{styles.set(card.dataset.chartId,select.value);const item=last.get(chart.id);if(item)window.renderDynamicCoalChart(chart.id,item.rows,{...item.chart,type:select.value})}; label.append(select); tools.append(label);
    const reset=card.querySelector('.cwx-card-size'); if(reset)reset.onclick=()=>{card.style.width='';card.style.height='';card.classList.remove('cwx-card-wide','cwx-card-large')};
  });
  new MutationObserver(enhance).observe(document.body,{subtree:true,childList:true}); enhance();
})();
