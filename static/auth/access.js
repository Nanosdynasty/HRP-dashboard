"use strict";
(() => {
  const originalFetch = window.fetch.bind(window);
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  let user;
  const ready = originalFetch("/api/auth/me", {cache:"no-store"}).then(async response => {
    if (!response.ok) { window.location.assign("/auth/login"); return null; }
    user = await response.json(); window.hrpAccess = user;
    if (user.enabled) window.sessionStorage?.removeItem('hrpAdminToken');
    if (user.enabled && user.status !== "approved") { window.location.assign("/auth/status"); return null; }
    return user;
  });
  window.hrpAuthReady = ready;
  window.fetch = async (input, init={}) => {
    const url = new URL(typeof input === "string" ? input : input.url, window.location.href);
    const sameOrigin = url.origin === window.location.origin;
    if (!sameOrigin) return originalFetch(input, init);
    const account = await ready;
    const method = String(init.method || (typeof input === "string" ? "GET" : input.method) || "GET").toUpperCase();
    const options = {...init};
    if (account?.enabled && (!['GET','HEAD','OPTIONS'].includes(method) || url.searchParams.get('force') === 'true')) {
      options.headers = new Headers(init.headers || (typeof input !== "string" ? input.headers : undefined));
      options.headers.set("X-CSRF-Token", account.csrf);
    }
    const response = await originalFetch(input, options);
    if (account?.enabled && response.status === 401) window.location.assign("/auth/login");
    return response;
  };
  const adminSelectors = '#coal-upload,#coal-upload-input,#coal-analysis-refresh,#news-refresh,#coastal-weather-refresh,#river-level-refresh,#npp-refresh,#pa-upload,[data-review],[data-admin-only]';
  const editSections = {
    'coal-upload':'india_coal', 'coal-upload-input':'india_coal', 'coal-analysis-refresh':'india_coal',
    'npp-refresh':'india_coal', 'news-refresh':'news', 'coastal-weather-refresh':'weather',
    'river-level-refresh':'rivers', 'pa-upload':'port_activity'
  };
  function hideAdminControls() {
    if (!user?.enabled) return;
    document.querySelectorAll(adminSelectors).forEach(node => {
      if (user.role === 'admin' && !user.sso) return;
      const section = editSections[node.id];
      if (section && user.permissions?.[section] === 'edit') return;
      const target = node.id === 'pa-upload' ? node.closest('details') || node : node;
      target.hidden = true;
    });
  }
  async function api(path, body) {
    const response = await window.fetch(path, body ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Access request failed.');
    return payload;
  }
  async function loadAccess() {
    const payload = await api('/api/admin/access');
    $('access-content').innerHTML = `<h3>Email invitations</h3><p>Removing an invitation prevents future approvals. Revoke the account separately to end existing access.</p>${payload.invitations.map(r => `<p>${escape(r.email)} · ${r.active ? 'Enabled' : 'Disabled'} <button data-invite="${escape(r.email)}" data-active="${r.active ? 'false' : 'true'}">${r.active ? 'Disable' : 'Enable'}</button></p>`).join('') || '<p>No invitations yet.</p>'}
      <h3>Microsoft accounts</h3><div class="access-scroll"><table><thead><tr><th>Account and verified identity</th><th>Access</th><th>Actions</th></tr></thead><tbody>${payload.accounts.map(r => `<tr><td>${escape(r.name)}<br>${escape(r.email || 'No email label supplied')}<details><summary>Identity identifiers</summary><code>Issuer: ${escape(r.issuer)}<br>Subject: ${escape(r.subject)}</code></details></td><td>${escape(r.status)} · ${escape(r.role)}</td><td><select aria-label="Role for ${escape(r.name)}" data-role="${r.id}"><option value="viewer" ${r.role === 'viewer' ? 'selected' : ''}>Viewer</option><option value="admin" ${r.role === 'admin' ? 'selected' : ''}>Administrator</option></select><button data-account="${r.id}" data-status="approved">${r.status === 'approved' ? 'Update role' : 'Approve identity'}</button><button data-account="${r.id}" data-status="revoked">Revoke</button></td></tr>`).join('')}</tbody></table></div>
      <details><summary>Recent access audit</summary>${payload.audit.map(r => `<p>${escape(new Date(r.occurred_at*1000).toISOString())} · ${escape(r.action)} · ${escape(r.target)}</p>`).join('')}</details>`;
  }
  function message(error) { $('access-message').textContent = error.message || String(error); }
  document.addEventListener('DOMContentLoaded', async () => {
    await ready;
    if (!user?.enabled) return;
    $('account-controls').hidden = false;
    $('account-label').textContent = `${user.email || user.name} · ${user.role}`;
    $('access-open').hidden = user.role !== 'admin' || user.sso;
    hideAdminControls();
    new MutationObserver(hideAdminControls).observe(document.body, {childList:true,subtree:true});
    $('account-logout').onclick = async () => {
      await api('/auth/logout', {}); window.location.assign('/auth/login');
    };
    $('access-open').onclick = async () => {
      $('access-panel').showModal(); try { await loadAccess(); } catch(error) { message(error); }
    };
    $('access-close').onclick = () => $('access-panel').close();
    $('access-invite').onsubmit = async event => {
      event.preventDefault();
      try { await api('/api/admin/access/invitations',{email:$('access-email').value}); $('access-email').value=''; await loadAccess(); message('Email added. The user must sign in, then you approve their identity.'); } catch(error) { message(error); }
    };
    $('access-content').onclick = async event => {
      const button = event.target.closest('button'); if (!button) return;
      try {
        if (button.dataset.invite) await api('/api/admin/access/invitations',{email:button.dataset.invite,active:button.dataset.active==='true'});
        if (button.dataset.account) {
          const role = document.querySelector(`[data-role="${button.dataset.account}"]`).value;
          if (!window.confirm(`${button.dataset.status === 'approved' ? 'Approve/update' : 'Revoke'} this specific Microsoft identity? Confirm its identifiers with the user before approval.`)) return;
          await api(`/api/admin/access/accounts/${button.dataset.account}`, {status:button.dataset.status,role});
        }
        await loadAccess(); message('Access updated. Changed accounts must sign in again.');
      } catch(error) { message(error); }
    };
  });
})();
