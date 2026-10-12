"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let csrf;
  async function api(path, body) {
    const response = await fetch(path, {cache:'no-store', ...(body ? {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)} : {})});
    const payload = await response.json();
    if(!response.ok) throw new Error(payload.detail || 'Request failed.');
    return payload;
  }
  function message(value) { $('auth-message').textContent = value; }
  function form(id, handler) {
    $(id)?.addEventListener('submit',async event=>{
      event.preventDefault(); const button=event.target.querySelector('button'); button.disabled=true;message('');
      try {await handler(Object.fromEntries(new FormData(event.target)));} catch(error){message(error.message);} finally{button.disabled=false;}
    });
  }
  const password = '<label>New dashboard password<input name="password" type="password" minlength="15" maxlength="128" autocomplete="new-password" required></label><p class="hint">15–128 characters. Password managers and paste are supported.</p>';
  async function status() {
    const container=$('request-status');
    let user;
    try {user=await api('/api/auth/me');} catch(error) {
      const browser=await api('/api/auth/browser');
      container.innerHTML='<p>Verify the same account you used to request access.</p><a class="button" href="/auth/verify">Verify Microsoft</a>'+(browser.google_available?' <a class="button secondary" href="/auth/google/verify">Verify Google / Gmail</a>':''); return;
    }
    csrf=user.csrf;
    const state = user.enrolment;
    const labels={unapproved:'Request access',pending:'Awaiting approval',rejected:'Rejected',revoked:'Revoked',setup_required:'Setup required',active:'Active'};
    container.innerHTML=`<p class="state-badge">${esc(labels[state] || state)}</p><p>${esc(user.name)}<br><strong>${esc(user.email)}</strong></p>`;
    if(state==='unapproved') {
      container.innerHTML+='<p>Your identity is verified. Your request will appear in the owner’s access area.</p><form id="request-form"><label>Name<input name="name" maxlength="200" required></label><label>Reason for access<textarea name="reason" minlength="10" maxlength="2000" required rows="4"></textarea></label><button>Submit request</button></form>';
      form('request-form',async data=>{await api('/api/auth/request',data);await status();});
    } else if(state==='pending') container.innerHTML+='<p>The owner will approve or reject your request and assign section permissions. No dashboard data is available yet.</p>';
    else if(['rejected','revoked'].includes(state)) container.innerHTML+='<p>Dashboard access is unavailable. Contact the owner if you need a review.</p>';
    else if(state==='setup_required') {
      container.innerHTML+='<p>Complete your password and phone authenticator setup to activate access.</p><form id="password-form">'+password+'<button>Create password</button></form><button id="enrol-start" type="button">Set up phone authenticator</button><section id="mfa-enrolment"></section>';
      form('password-form',async data=>{await api('/api/auth/password',data);$('password-form').hidden=true;message('Password created. Set up your authenticator next.');});
      $('enrol-start').onclick=async()=>{
        try {
          await api('/api/auth/mfa/enrol',{});
          $('password-form').hidden=true;
          $('mfa-enrolment').innerHTML='<h2>Enrol your authenticator</h2><p>In Microsoft Authenticator choose “Other account”, then scan this QR code. Other TOTP authenticator apps also work.</p><img class="mfa-qr" src="/api/auth/mfa/qr" alt="Scan this private QR code with your authenticator"><form id="confirm-form"><label>Six-digit code<input name="code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" autocomplete="one-time-code" required></label><button>Confirm authenticator</button></form>';
          form('confirm-form',async data=>{
            const result=await api('/api/auth/mfa/confirm',data);
            container.innerHTML='<h2>Save your recovery codes</h2><p>These ten codes are displayed once. Store them in a password manager. Each code works once when you cannot use your phone.</p><pre class="recovery-codes">'+result.recovery_codes.map(esc).join('\n')+'</pre><a class="button" href="/">I saved my codes — open dashboard</a>';
            $('auth-message').textContent='Authenticator confirmed. Your account is active.';
          });
        } catch(error){message(error.message);}
      };
    } else if(state==='active') {
      container.innerHTML+=user.authenticated?'<a class="button" href="/">Open dashboard</a>':'<a class="button" href="/auth/login">Log in with password and authenticator</a>';
      if(!user.authenticated) {
        container.innerHTML+='<details><summary>Reset dashboard password</summary><p>Use the reset link sent to your approved email address and a code from your authenticator. If mail is not configured, identity verification plus an authenticator or existing recovery code remains available.</p><form id="reset-form">'+password+'<label>Authenticator / existing recovery code<input name="code" autocomplete="one-time-code" maxlength="64" required></label><button>Reset password</button></form><button id="lost-factor" type="button">I lost my phone</button></details>';
        form('reset-form',async data=>{await api('/api/auth/reset',data);window.location.assign('/auth/login');});
        $('lost-factor').onclick=async()=>{try{await api('/api/auth/lost-factor',{});message('Lost-factor reset requested. The owner must approve it. Return using fresh identity verification after approval.');}catch(error){message(error.message);}};
      }
    }
  }
  async function admin() {
    const me=await api('/api/auth/me');csrf=me.csrf;
    const payload=await api('/api/admin/access');
    $('requests-admin').innerHTML=`<p class="state-badge">${payload.pending_count} pending requests</p>`+payload.accounts.map(row=>{
      return `<article class="request-card"><h2>${esc(row.name)}</h2><p><strong>${esc(row.email)}</strong> · ${esc(row.status)} · ${esc(row.enrolment)}</p><p>Submitted: ${row.submitted_at?esc(new Date(row.submitted_at*1000).toLocaleString()):'No signup request'}</p><p>${esc(row.reason || '')}</p><details><summary>Verified sign-in identity</summary><p>Issuer: ${esc(row.issuer)}<br>Subject: ${esc(row.subject)}</p></details>${row.owner?'<p>Owner · all sections · administrator. Owner access cannot be reduced.</p>':`<form data-account="${row.id}"><div class="grants-grid">${Object.entries(payload.sections).map(([key,label])=>`<label>${esc(label)}<select name="${esc(key)}">${['hidden','view','edit'].map(level=>`<option value="${level}" ${row.permissions[key]===level?'selected':''}>${level[0].toUpperCase()+level.slice(1)}</option>`).join('')}</select></label>`).join('')}</div><div class="admin-actions"><button name="decision" value="approved">Approve / save permissions</button><button name="decision" value="rejected" class="secondary">Reject</button><button name="decision" value="revoked" class="danger">Revoke</button></div></form>${row.reset_requested_at&&!row.reset_approved_at?`<p>Lost-factor reset requested ${esc(new Date(row.reset_requested_at*1000).toLocaleString())}</p><button data-reset="${row.id}">Approve lost-factor reset</button>`:''}`}</article>`;
    }).join('')+'<details><summary>Access audit history</summary>'+payload.audit.map(row=>`<p>${esc(new Date(row.occurred_at*1000).toLocaleString())} · ${esc(row.action)} · ${esc(row.target)}</p>`).join('')+'</details>';
    $('requests-admin').querySelectorAll('form[data-account]').forEach(node=>node.onsubmit=async event=>{
      event.preventDefault();const button=event.submitter;button.disabled=true;
      try {await api('/api/admin/access/accounts/'+node.dataset.account,{status:button.value,permissions:Object.fromEntries(new FormData(node))});await admin();message('Access updated. Existing sessions were invalidated.');}catch(error){message(error.message);}finally{button.disabled=false;}
    });
    $('requests-admin').querySelectorAll('[data-reset]').forEach(button=>button.onclick=async()=>{
      if(!window.confirm('Approve this identity’s lost-factor reset? This ends its sessions and requires a new password and authenticator.'))return;
      try{await api('/api/admin/access/accounts/'+button.dataset.reset+'/reset-factor',{});await admin();message('Reset approved. The user must verify the same identity again and repeat setup.');}catch(error){message(error.message);}
    });
  }
  async function init() {
    const view=document.querySelector('[data-view]')?.dataset.view;
    if(view==='status')return status();
    if(view==='admin')return admin();
    if(view==='login') {
      csrf=(await api('/api/auth/browser')).csrf;
      form('login-form',async data=>{const result=await api('/api/auth/login',data);csrf=result.csrf;$('login-form').hidden=true;$('challenge-form').hidden=false;$('challenge-form').elements.code.focus();});
      form('challenge-form',async data=>{await api('/api/auth/challenge',data);window.location.assign('/');});
      form('email-reset-request-form',async data=>{const result=await api('/api/auth/email-reset/request',data);message(result.message);});
    }
    if(view==='email-reset') {
      const token=window.location.hash.slice(1);
      window.history.replaceState(null,'',window.location.pathname);
      if(!token){message('The reset link is missing or expired. Request a new link.');return;}
      csrf=(await api('/api/auth/browser')).csrf;
      form('email-reset-complete-form',async data=>{await api('/api/auth/email-reset/complete',{...data,token});message('Password updated. Please log in again.');window.location.assign('/auth/login');});
    }
  }
  init().catch(error=>message(error.message));
})();
