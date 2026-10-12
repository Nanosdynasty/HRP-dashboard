/* Expanded source-backed news and research workspace. */
(() => {
  const desk={view:'overview',page:1,payload:null,query:'',timer:null,searchTimer:null,serial:0,loading:false};
  const el=id=>document.getElementById(id), esc=value=>escapeHtml(String(value??''));
  const safe=url=>/^https?:\/\//i.test(url||'')?url:'#';
  const read=(key,fallback)=>{try{return JSON.parse(localStorage.getItem(key))||fallback;}catch{return fallback;}};
  const write=(key,value)=>{try{localStorage.setItem(key,JSON.stringify(value));}catch{el('intelligence-status').textContent='Browser storage unavailable; this view remains usable.';}};
  function params(){
    const p=new URLSearchParams(new FormData(el('intelligence-filters')));p.delete('');p.set('page',desk.page);p.set('q',el('news-search').value.trim());
    p.set('topic',['chartering','cargo_trade','ports','fleet_snp','policy','weather'].includes(desk.view)?desk.view:(state.newsTopic||'all'));
    if(desk.view==='reports')p.set('content_type','report');
    if(desk.view==='bookmarks'){p.set('article_ids',read('hrp-news-bookmarks',[]).map(r=>r.id).join(',')||'__none__');p.set('days','0');}
    return p;
  }
  function fillFacets(payload){
    const f=payload.facets||{},names={country:'countries',port:'ports',vessel:'vessel_classes',publisher:'publishers',language:'languages',commodity_group:'commodity_groups'};
    Object.entries(names).forEach(([name,field])=>{const select=el('intelligence-filters').elements[name],value=select.value,blank=name==='commodity_group'?'all':'';select.innerHTML=`<option value="${blank}">All ${esc(name.replace('_',' '))}</option>`+(f[field]||[]).map(v=>`<option value="${esc(v)}">${esc(v.replaceAll('_',' '))}</option>`).join('');if([...select.options].some(o=>o.value===value))select.value=value;});
  }
  const date=row=>row.published_at?newsPublishedLabel(row.published_at):`Publication date not supplied${row.reporting_period?' · reporting period '+row.reporting_period:''}`;
  function card(row){
    const saved=read('hrp-news-bookmarks',[]).some(x=>x.id===row.id);
    return `<article class="intelligence-article"><div class="news-row-meta"><span>${esc(row.source_name)}</span><span>${esc(row.content_type||'news')}</span><span>${esc(date(row))}</span></div><a href="${esc(safe(row.link))}" target="_blank" rel="noopener noreferrer"><h2>${esc(row.title)}</h2></a><p>${esc(row.description)}</p><div class="intelligence-tags">${[...(row.commodity_groups||[]),...(row.countries||[]),...(row.vessel_classes||[])].slice(0,8).map(t=>`<span>${esc(t.replaceAll('_',' '))}</span>`).join('')}</div><small>${esc(row.evidence_level||'metadata only')} · ${esc(row.language||'Language unverified')}${row.related_coverage_count>1?' · '+row.related_coverage_count+' related articles':''}</small><footer><button data-news-detail="${esc(row.id)}">Evidence &amp; related coverage</button><button data-news-bookmark="${esc(row.id)}">${saved?'Remove bookmark':'Bookmark'}</button></footer></article>`;
  }
  function coverage(p){
    return `<p>${esc(p.coverage_note)}</p><p>Archive contains ${p.archive_total||0} collected records. Earliest dated record: ${esc(p.archive_start||'Not available')}.</p><div class="intelligence-source-grid">${[...(p.providers||[]),...(p.reports_sources||[])].map(s=>`<article><h3>${esc(s.label||s.name)}</h3><b>${esc(s.status||'Not checked')}</b><p>${Number(s.fetched??s.discovered??0)} items in the latest source result</p>${s.error?`<p class="intelligence-error">${esc(s.error)}</p>`:''}${s.url?`<a href="${esc(safe(s.url))}" target="_blank" rel="noopener">Open source</a>`:''}</article>`).join('')}</div><p>Collection audit: ${esc(JSON.stringify(p.audit||{}))}. No target article quota is enforced. Related headline copies are not independent confirmation.</p>`;
  }
  async function render(){
    const p=desk.payload;if(!p)return;
    el('news-sidebar-status').textContent=`${p.total} matching records`;
    el('news-subtitle').textContent=`${p.total} matching records · ${p.archive_total} in collected archive · ${p.event_count} headline groups · last source check ${p.fetched_at?new Date(p.fetched_at).toLocaleString():'not completed'}`;
    el('intelligence-export').href=`/api/news/export.csv?snapshot_id=${encodeURIComponent(p.snapshot_id)}`;
    el('news-metrics').innerHTML=[['Matching records',p.total],['Collected archive',p.archive_total],['Headline groups',p.event_count],['Healthy sources',(p.providers||[]).filter(x=>x.status?.startsWith('healthy')).length]].map(([label,value])=>`<article><span>${esc(label)}</span><strong>${value||0}</strong></article>`).join('');
    document.querySelectorAll('[data-intelligence-view]').forEach(b=>b.classList.toggle('active',b.dataset.intelligenceView===desk.view));
    if(desk.view==='sources'){el('news-feed').innerHTML=coverage(p);return;}
    if(desk.view==='brief'){
      el('news-feed').innerHTML='<p>Building a source digest for the selected publication window…</p>';
      const response=await fetch(`/api/news/brief?snapshot_id=${encodeURIComponent(p.snapshot_id)}`);const brief=await response.json();if(!response.ok)throw new Error(brief.detail||'Brief unavailable');if(desk.view!=='brief')return;
      el('news-feed').innerHTML=`<div class="intelligence-pagination"><button data-brief-days="1">Daily digest</button><button data-brief-days="7">Weekly digest</button></div><p class="intelligence-note">${esc(brief.method)}. Facts and causal interpretations are not inferred from headlines.</p>`+brief.groups.map(g=>`<section class="intelligence-brief"><h2>${esc(g.title)}</h2><p>${g.article_count} articles · ${g.sources} publishers</p>${g.evidence.map(r=>`<article><a href="${esc(safe(r.link))}" target="_blank" rel="noopener"><h3>${esc(r.title)}</h3></a><p>${esc(r.description)}</p><small>${esc(r.source_name)} · ${esc(r.published_at||'Date unavailable')}</small></article>`).join('')||'<p>No source evidence in the selected period.</p>'}<small>${esc(g.interpretation)}</small></section>`).join('');document.querySelectorAll('[data-brief-days]').forEach(b=>b.onclick=()=>{el('intelligence-filters').elements.days.value=b.dataset.briefDays;desk.page=1;load();});return;
    }
    const rows=p.rows;
    let overview='';
    if(desk.view==='overview')overview=`<section class="intelligence-overview"><h2>Coverage in this selection</h2><p>Explore the topic tabs for complete coverage. Publisher descriptions are retained as metadata; reports have separate document-review controls.</p><div class="intelligence-tags">${Object.entries(p.facets?.countries||[]).slice(0,16).map(([,c])=>`<span>${esc(c)}</span>`).join('')}</div></section>`;
    el('news-feed').innerHTML=overview+`<div class="intelligence-articles">${rows.map(card).join('')||'<p>No records match these filters. Widen the publication window or reset the filters. Source failures are listed under Sources & coverage.</p>'}</div>`+(false?'':`<div class="intelligence-pagination"><button id="intelligence-prev" ${p.page<=1?'disabled':''}>Previous</button><span>Page ${p.page} of ${p.pages} · ${p.total} matching records</span><button id="intelligence-next" ${p.page>=p.pages?'disabled':''}>Next</button></div>`);
    el('intelligence-prev')?.addEventListener('click',()=>{desk.page--;load();});el('intelligence-next')?.addEventListener('click',()=>{desk.page++;load();});
    document.querySelectorAll('[data-news-detail]').forEach(b=>b.addEventListener('click',()=>detail(b.dataset.newsDetail)));
    document.querySelectorAll('[data-news-bookmark]').forEach(b=>b.addEventListener('click',()=>{const id=b.dataset.newsBookmark,stored=read('hrp-news-bookmarks',[]),row=rows.find(r=>r.id===id);write('hrp-news-bookmarks',stored.some(r=>r.id===id)?stored.filter(r=>r.id!==id):[...stored,row]);if(desk.view==='bookmarks')load();else render();}));
  }
  async function detail(id){
    const response=await fetch(`/api/news/articles/${encodeURIComponent(id)}`);const row=await response.json();if(!response.ok){el('intelligence-status').textContent=row.detail;return;}
    const dialog=document.createElement('dialog');dialog.className='intelligence-dialog';document.body.appendChild(dialog);
    function show(r){dialog.innerHTML=`<button data-close>Close</button><h2>${esc(r.title)}</h2><p>${esc(r.description)}</p><p>${esc(r.evidence_level)} · first discovered ${esc(r.discovered_at)} · ${r.revision_count||0} recorded revisions</p><a href="${esc(safe(r.link))}" target="_blank" rel="noopener">Open original</a>${r.content_type==='report'?'<p>Official reports can be reviewed when an accessible PDF is available. Extracted pages remain source text, not an AI market forecast.</p><button data-review>Review official PDF</button>':''}<p data-review-status role="status"></p>${(r.document_evidence||[]).map(e=>`<details><summary>Page ${e.page} · <a href="${esc(safe(e.source_url))}" target="_blank" rel="noopener">Source page</a></summary><p>${esc(e.excerpt)}</p></details>`).join('')}<h3>Related coverage</h3>${(r.related_coverage||[]).map(x=>`<p><a href="${esc(safe(x.link))}" target="_blank" rel="noopener">${esc(x.title)}</a> · ${esc(x.source_name)}</p>`).join('')||'<p>No exact headline matches collected. This does not mean the event has no other coverage.</p>'}`;
      dialog.querySelector('[data-close]').onclick=()=>{dialog.close();dialog.remove();};dialog.querySelector('[data-review]')?.addEventListener('click',async event=>{event.target.disabled=true;dialog.querySelector('[data-review-status]').textContent='Downloading and extracting the official report…';try{const response=await fetch(`/api/news/articles/${encodeURIComponent(id)}/document`,{method:'POST'}),data=await response.json();if(!response.ok)throw new Error(data.detail);show({...r,...data});}catch(e){dialog.querySelector('[data-review-status]').textContent=e.message;event.target.disabled=false;}});
    }show(row);dialog.showModal();
  }
  async function load(force=false,poll=false){
    if(desk.loading){if(!poll)desk.pending=true;return;}desk.loading=true;const serial=++desk.serial;
    if(!poll)el('intelligence-status').textContent=force?'Refreshing sources; keeping the current view until new results arrive…':'Loading the archive…';
    try{
      if(force){const refresh=await fetch('/api/news/refresh',{method:'POST'});if(!refresh.ok)throw new Error('Source refresh failed; existing archive retained');}
      const response=await fetch(`/api/news?${params()}`),payload=await response.json();if(!response.ok)throw new Error(payload.detail||'Archive unavailable');if(serial!==desk.serial)return;
      if(poll){if(payload.fetched_at!==desk.payload?.fetched_at)el('intelligence-update').hidden=false;return;}
      desk.payload=payload;state.newsPayload=payload;desk.page=payload.page;fillFacets(payload);await render();el('intelligence-update').hidden=true;
      el('intelligence-status').textContent=`${payload.last_error?'Some sources failed; previous records retained. ':''}${payload.coverage_note}`;
    }catch(e){if(!poll)el('intelligence-status').textContent=e.message+' · Previous results remain available.';}finally{desk.loading=false;if(desk.pending){desk.pending=false;load();}}
  }
  window.openNewsIntelligence=name=>{desk.view='latest';desk.page=1;el('intelligence-filters').reset();el('news-search').value=name;state.newsTopic='all';activateMode('news');};
  window.loadNews=load;
  window.renderNewsWorkspace=()=>{clearTimeout(desk.searchTimer);desk.page=1;desk.searchTimer=setTimeout(()=>load(),300);};
  document.addEventListener('DOMContentLoaded',()=>{
    el('intelligence-filters').onsubmit=e=>{e.preventDefault();desk.page=1;load();};
    document.querySelectorAll('[data-intelligence-view]').forEach(b=>b.onclick=()=>{desk.view=b.dataset.intelligenceView;state.newsTopic='all';desk.page=1;if(desk.view==='reports')el('intelligence-filters').elements.days.value='90';load();});
    el('intelligence-reset').onclick=()=>{el('intelligence-filters').reset();el('news-search').value='';state.newsTopic='all';desk.page=1;load();};
    el('intelligence-new-items').onclick=()=>load();
    function saved(){const views=read('hrp-news-views',[]);el('intelligence-saved').innerHTML='<option value="">Choose a saved view</option>'+views.map((v,i)=>`<option value="${i}">${esc(v.name)}</option>`).join('');}
    el('intelligence-save-view').onclick=()=>{const views=read('hrp-news-views',[]);views.push({name:`${desk.view} · ${new Date().toLocaleString()}`,view:desk.view,params:Object.fromEntries(params())});write('hrp-news-views',views);saved();};
    el('intelligence-saved').onchange=e=>{if(e.target.value==='')return;const v=read('hrp-news-views',[])[Number(e.target.value)];if(!v)return;desk.view=v.view;for(const [k,value] of Object.entries(v.params)){if(el('intelligence-filters').elements[k])el('intelligence-filters').elements[k].value=value;}el('news-search').value=v.params.q||'';desk.page=1;load();};saved();
    desk.timer=setInterval(()=>{if(state.mode==='news'&&!document.hidden&&desk.payload)load(false,true);},60000);
  });
})();
