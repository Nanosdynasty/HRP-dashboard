/* Source-backed outlook, shared table/map filters and snapshot-consistent export. */
const portOutlook = {payload: null, map: null, markers: null, page: 0, sort: "assessment", direction: "asc", request: 0};
const outlookColors = {"Confirmed restriction": "#b51f36", "Published limit exceeded": "#bc5b14", "Weather watch": "#ac7600", "Not assessed": "#77828e", "No trigger identified": "#287058"};

function outlookQuery() {
  const params = new URLSearchParams(new FormData(document.getElementById("outlook-filters")));
  params.set("sort", portOutlook.sort);
  params.set("direction", portOutlook.direction);
  params.set("limit", "50");
  params.set("offset", String(portOutlook.page * 50));
  return params;
}
function outlookDate(value) {
  if (!value) return "Not available";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? String(value) : date.toISOString().replace("T", " ").replace(/\.\d+Z$/, " UTC");
}
function outlookLink(url, label) {
  try { if (new URL(url).protocol !== "https:") return ""; } catch { return ""; }
  return `<a href="${escapeAttr(url)}" target="_blank" rel="noopener">${escapeHtml(label)}</a>`;
}
function outlookBadge(row) {
  return `<span class="outlook-badge" style="--assessment-color:${outlookColors[row.assessment] || '#77828e'}">${escapeHtml(row.assessment)}</span>`;
}

async function loadPortOutlook() {
  const request = ++portOutlook.request;
  const status = document.getElementById("outlook-status");
  if (!portOutlook.payload) status.textContent = "Loading official forecast and notice evidence…";
  try {
    const response = await fetch(`/api/port-disruption-outlook?${outlookQuery()}`);
    if (!response.ok) throw new Error(`Outlook request failed (${response.status})`);
    const payload = await response.json();
    if (request !== portOutlook.request) return;
    if (payload.total && !payload.rows.length && portOutlook.page) {
      portOutlook.page = 0; return loadPortOutlook();
    }
    portOutlook.payload = payload;
    renderPortOutlook();
  } catch (error) {
    if (request === portOutlook.request) status.textContent = `${error.message}. ${portOutlook.payload ? 'Last displayed snapshot retained; refresh failed.' : 'Outlook not assessed.'}`;
  }
}

function renderPortOutlook() {
  const payload = portOutlook.payload;
  const rows = payload.rows;
  const total = payload.total ?? rows.length;
  const pages = Math.max(1, Math.ceil(total / 50));
  portOutlook.page = Math.min(portOutlook.page, pages - 1);
  document.getElementById("outlook-status").textContent = `${payload.filtered_port_count} ports · ${total} operation / scope / horizon rows · inventory ${payload.inventory_count} dry-bulk ports · assessed ${outlookDate(payload.generated_at)}. Sources refresh in the background; this view polls every minute while open.`;
  const headings = [["port_name", "Port / documented scope"], ["country", "Country"], ["operation", "Operation"], ["forecast_window", "Horizon"], ["assessment", "Assessment"]];
  document.getElementById("outlook-table").innerHTML = rows.length ? `<table><thead><tr>${headings.map(([field, title]) => `<th scope="col"><button type="button" data-outlook-sort="${field}">${title}${portOutlook.sort === field ? portOutlook.direction === 'asc' ? ' ↑' : ' ↓' : ''}</button></th>`).join("")}<th scope="col">Evidence / coverage</th><th scope="col">Actual status</th></tr></thead><tbody>${(payload.limit ? rows : rows.slice(portOutlook.page * 50, (portOutlook.page + 1) * 50)).map(row => `<tr><td><button type="button" class="outlook-row-link" data-outlook-row="${escapeAttr(row.row_id)}">${escapeHtml(row.port_name)}</button><small>${escapeHtml(row.scope_name)} · ${escapeHtml(row.scope_type)}</small></td><td>${escapeHtml(row.country_name || row.country)}</td><td>${escapeHtml(row.operation)}<small>${escapeHtml(row.operation_group)}</small></td><td>${escapeHtml(row.forecast_window.replace('-', '–'))}h</td><td>${outlookBadge(row)}</td><td>${escapeHtml(row.weather_resolution.join('; ') || 'Forecast unavailable')}<small>${escapeHtml(row.coverage_limitations.join('; ') || 'Complete screening evidence')}</small></td><td>${escapeHtml(row.actual_operating_status)}</td></tr>`).join("")}</tbody></table>` : `<p>No outlook rows match these filters.</p>`;
  document.getElementById("outlook-pagination").innerHTML = `<button type="button" id="outlook-prev" ${portOutlook.page ? '' : 'disabled'}>Previous</button><span>Page ${portOutlook.page + 1} / ${pages} · export includes all ${total} filtered rows</span><button type="button" id="outlook-next" ${portOutlook.page + 1 < pages ? '' : 'disabled'}>Next</button>`;
  document.getElementById("outlook-prev").onclick = () => {portOutlook.page--; loadPortOutlook();};
  document.getElementById("outlook-next").onclick = () => {portOutlook.page++; loadPortOutlook();};
  document.querySelectorAll("[data-outlook-sort]").forEach(button => button.onclick = () => {
    portOutlook.direction = portOutlook.sort === button.dataset.outlookSort && portOutlook.direction === "asc" ? "desc" : "asc";
    portOutlook.sort = button.dataset.outlookSort; portOutlook.page = 0; loadPortOutlook();
  });
  document.querySelectorAll("[data-outlook-row]").forEach(button => button.onclick = () => showOutlookRow(rows.find(r => r.row_id === button.dataset.outlookRow)));
  const statuses = payload.notice_source_status || {};
  document.getElementById("outlook-source-status").innerHTML = `<p>${escapeHtml(payload.methodology)}</p><p>${payload.unmatched_records.length} unmatched forecast locations excluded from port conclusions · ${payload.historical_forecast_count || 0} expired forecast intervals excluded from current alerts.</p><ul>${payload.sources.map(source => `<li>${outlookLink(source.url, source.authority)} · ${escapeHtml(source.status || 'Authority source link; structured adapter not available')} · last successful check ${escapeHtml(outlookDate((statuses[source.id] || source).last_success_at))}${source.error ? ' · ' + escapeHtml(source.error) : ''}</li>`).join('')}</ul>${Object.keys(payload.source_errors).length ? `<p>Weather source errors: ${escapeHtml(JSON.stringify(payload.source_errors))}. Last successful timestamps remain unchanged.</p>` : ''}<details><summary>Unmatched forecast locations</summary>${payload.unmatched_records.map(r => `<p>${escapeHtml(r.name)} · ${escapeHtml(r.country)} · ${escapeHtml(r.reason)}</p>`).join('')}</details>`;
  renderOutlookMap(payload.map_markers || rows);
}

function renderOutlookMap(rows) {
  if (!portOutlook.map) {
    portOutlook.map = L.map("outlook-map").setView([10, 35], 2);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {attribution: '&copy; OpenStreetMap &copy; CARTO', maxZoom: 18}).addTo(portOutlook.map);
    portOutlook.markers = L.layerGroup().addTo(portOutlook.map);
  }
  portOutlook.markers.clearLayers();
  const ranks = Object.keys(outlookColors);
  const grouped = new Map();
  rows.forEach(row => {
    if (!grouped.has(row.port_id) || ranks.indexOf(row.assessment) < ranks.indexOf(grouped.get(row.port_id).assessment)) grouped.set(row.port_id, row);
  });
  grouped.forEach(row => {
    if (row.latitude == null || row.longitude == null) return;
    L.circleMarker([row.latitude, row.longitude], {radius: 5, color: outlookColors[row.assessment], fillOpacity: .8, weight: 1}).bindTooltip(`${escapeHtml(row.port_name)} · ${escapeHtml(row.assessment)}<br>Highest-priority filtered operation; click for scope`).on("click", async () => {
      if (row.provenance) return showOutlookRow(row);
      try {
        const response = await fetch(`/api/port-disruption-outlook?port=${encodeURIComponent(row.port_id)}`);
        if (!response.ok) throw new Error('Port outlook unavailable');
        const data = await response.json(); showOutlookRow(data.rows.find(r => r.row_id === row.row_id));
      } catch (error) {document.getElementById('outlook-status').textContent = error.message;}
    }).addTo(portOutlook.markers);
  });
  setTimeout(() => portOutlook.map.invalidateSize(), 0);
}

function outlookRowDetail(row) {
  return `<h3>${escapeHtml(row.port_name)} · ${escapeHtml(row.scope_name)}</h3><p>${outlookBadge(row)} · ${escapeHtml(row.operation)} · ${escapeHtml(row.forecast_window.replace('-', '–'))} hours</p><p><strong>Actual operating status:</strong> ${escapeHtml(row.actual_operating_status)}</p><p>Documented role: ${escapeHtml(row.role)} · Cargoes: ${escapeHtml(row.commodities.join(', ') || 'Not documented')}</p><p>${escapeHtml(row.weather_resolution.join('; ') || 'Forecast unavailable')}</p><p>${escapeHtml(row.assessment_basis.join('; ') || 'No sufficient trigger evidence for this scope / horizon.')}</p>${row.potential_windows.length ? '<h4>Potential disruption windows (UTC)</h4>' + row.potential_windows.map(w => `<p>${escapeHtml(outlookDate(w.start))} → ${escapeHtml(outlookDate(w.end))}<br>${escapeHtml(w.assessment)} · ${escapeHtml(w.resolution)}<br>${escapeHtml(w.basis.join('; '))}</p>`).join('') : ''}<p><strong>Coverage limitations:</strong> ${escapeHtml(row.coverage_limitations.join('; ') || 'None identified for screening')}</p><p>Last successful forecast download: ${escapeHtml(outlookDate(row.freshness.latest_successful_forecast_download))}</p>${row.applicable_rules.map(r => `<p>${outlookLink(r.source_url, r.source_title || r.id)} · version ${escapeHtml(r.version)} · published ${escapeHtml(r.publication_date)}<br>${escapeHtml(r.evaluation)}</p>`).join('')}${row.cargo_provenance ? `<p>${outlookLink(row.cargo_provenance.source_url, 'Documented cargo categories')} · ${escapeHtml(row.cargo_provenance.basis)}</p>` : ''}<h4>Forecast and authority evidence</h4>${row.provenance.map(p => `<p>${outlookLink(p.source_url, p.authority || 'Official forecast')} · issued ${escapeHtml(p.issued_at || 'Not supplied')} · successful retrieval ${escapeHtml(outlookDate(p.fetched_at))}<br>Valid ${escapeHtml(outlookDate(p.valid_from))} → ${escapeHtml(outlookDate(p.valid_to))}${p.source_error ? '<br>Source error: ' + escapeHtml(p.source_error) : ''}</p>`).join('')}${row.notices.map(n => `<p>${outlookLink(n.source_url, n.summary)} · ${escapeHtml(n.status)} · ${escapeHtml(n.lifecycle)}<br>Published ${escapeHtml(n.publication_date_resolution ? (n.issued_at || '').slice(0,10) + ' · ' + n.publication_date_resolution : outlookDate(n.issued_at))} · effective dates ${escapeHtml(outlookDate(n.effective_from))} → ${escapeHtml(outlookDate(n.effective_to))}</p>`).join('')}<p>${(row.source_links || []).map((url,index) => outlookLink(url, 'Reference source ' + (index + 1))).join(' · ')}</p>${(row.specification_sources || []).map(s => outlookLink(s.url, s.title)).join(' · ')}<p class="detail-note">Planning evidence only. No delay hours, disruption probabilities or operational actions are inferred.</p>`;
}
function showOutlookRow(row) {
  if (!row) return;
  const detail = document.getElementById("outlook-detail");
  detail.hidden = false;
  detail.innerHTML = `<button type="button" id="outlook-close-detail">Close detail</button><button type="button" id="outlook-open-port">Open port and berth details</button>${outlookRowDetail(row)}`;
  document.getElementById("outlook-close-detail").onclick = () => {detail.hidden = true;};
  document.getElementById("outlook-open-port").onclick = () => showPortCard({id: row.port_id, name: row.port_name});
  detail.scrollIntoView({behavior: "smooth", block: "nearest"});
}

async function loadPortCardOutlook(id) {
  try {
    const response = await fetch(`/api/port-disruption-outlook?port=${encodeURIComponent(id)}`);
    if (!response.ok) throw new Error(`Outlook unavailable (${response.status})`);
    const payload = await response.json();
    const container = document.getElementById("port-outlook-card");
    if (!container || container.dataset.portId !== String(id)) return;
    container.innerHTML = `<h3>Dry-bulk disruption outlook</h3><p>Weather risk and actual restrictions are separate. Berths share port-area forecasts unless stated otherwise.</p>${payload.rows.length ? payload.rows.map(row => `<details><summary>${escapeHtml(row.scope_name)} · ${escapeHtml(row.operation)} · ${escapeHtml(row.forecast_window.replace('-', '–'))}h · ${escapeHtml(row.assessment)}</summary>${outlookRowDetail(row)}</details>`).join('') : '<p>Not assessed: this port is outside the existing dry-bulk inventory.</p>'}`;
  } catch (error) {
    const container = document.getElementById("port-outlook-card");
    if (container?.dataset.portId === String(id)) container.textContent = `${error.message}. Not assessed.`;
  }
}

document.getElementById("outlook-filters").addEventListener("submit", event => {event.preventDefault(); portOutlook.page = 0; loadPortOutlook();});
document.getElementById("outlook-refresh").onclick = loadPortOutlook;
document.getElementById("outlook-export").onclick = async () => {
  if (!portOutlook.payload) return;
  const params = new URLSearchParams(portOutlook.payload.filters);
  params.set("snapshot_id", portOutlook.payload.snapshot_id);
  try {
    const response = await fetch(`/api/port-disruption-outlook/export.csv?${params}`);
    if (!response.ok) throw new Error(response.status === 409 ? 'Snapshot expired. Refresh view before exporting.' : 'Export failed');
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a'); link.href = url; link.download = 'port-disruption-outlook.csv'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {document.getElementById('outlook-status').textContent = error.message;}
};
document.getElementById("outlook-history-load").onclick = async () => {
  try {
    const params = outlookQuery(); params.set('historical', 'true');
    const response = await fetch(`/api/port-disruption-outlook?${params}`);
    if (!response.ok) throw new Error('Historical view unavailable');
    const payload = await response.json();
    const rows = payload.historical_forecasts;
    document.getElementById('outlook-history').innerHTML = `<p>${rows.length} historical intervals. Expired forecasts never create current map alerts. Showing first 100.</p>${rows.slice(0,100).map(r => `<p>${escapeHtml(r.port_name)} · ${escapeHtml(outlookDate(r.valid_from))} → ${escapeHtml(outlookDate(r.valid_to))} · ${escapeHtml(r.label)} · ${outlookLink(r.source_url, 'Source')}</p>`).join('')}`;
  } catch (error) {document.getElementById('outlook-history').textContent = error.message;}
};
