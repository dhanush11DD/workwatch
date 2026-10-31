import { $, $$, S, t, esc, icon, api, toast, fail, modal, formModal, confirmBox, isManager, ago, fmtTs, fmtDay, inr, opt, field, empty, copyText,
  STATES, STATE_COLOR, stateLabel, todayIST } from '../core.js';
import { mount, refreshMe } from '../main.js';
import { renderWorkers, renderCameras } from './org.js';

/* Settings tabs (spec §17.1–17.15) with the §17.16 access matrix: who can see (R) or change (W) each tab. */
const TABS = [
  ['profile', 'Profile', 'user', { manager: 'W', reviewer: 'W' }],
  ['organization', 'Organization', 'building', { manager: 'W', reviewer: '-' }],
  ['team', 'Team & access', 'users', { manager: 'W', reviewer: 'R' }],
  ['workers', 'Workers', 'user', { manager: 'W', reviewer: 'R' }],
  ['cameras', 'Cameras', 'cctv', { manager: 'W', reviewer: '-' }],
  ['zones', 'Zone templates', 'map', { manager: 'W', reviewer: '-' }],
  ['rules', 'Analysis rules', 'sliders', { manager: 'W', reviewer: 'R' }],
  ['review', 'Review preferences', 'review', { manager: 'W', reviewer: 'R' }],
  ['delivery', 'Reports & delivery', 'send', { manager: 'W', reviewer: '-' }],
  ['notifications', 'Notifications', 'bell', { manager: 'W', reviewer: '-' }],
  ['privacy', 'Privacy & consent', 'shield', { manager: 'W', reviewer: 'R' }],
  ['audit', 'Audit trail', 'history', { manager: 'R', reviewer: '-' }],
  ['billing', 'Billing & usage', 'card', { manager: 'W', reviewer: '-' }],
  ['integrations', 'Integrations', 'plug', { manager: 'R', reviewer: '-' }],
  ['danger', 'Danger zone', 'alert', { manager: 'W', reviewer: '-' }],
];
const access = id => TABS.find(x => x[0] === id)?.[3][S.me.role] || '-';

let SET = null;
export async function settingsPage(tab) {
  if (access(tab) === '-') tab = 'profile';
  SET = await api('/api/settings');
  const visible = TABS.filter(x => x[3][S.me.role] !== '-');
  const el = mount('settings', `<a href="#/settings" style="text-decoration:none">${t('nav.settings')}</a>${icon('chevron', 'ic12')}<b>${esc(TABS.find(x => x[0] === tab)[1])}</b>`, `
    <div class="page-head"><div><h1>${t('nav.settings')}</h1><p>${esc(S.me.org.name)} · ${access(tab) === 'R' ? 'read-only for your role' : 'changes are recorded in the audit trail'}</p></div></div>
    <div class="settings"><nav class="settings-nav">${visible.map(([id, l, ic, a]) => `<a href="#/settings/${id}" class="${id === tab ? 'active' : ''}">${icon(ic)}${l}${a[S.me.role] === 'R' ? `<span class="lock">${icon('eye', 'ic12')}</span>` : ''}</a>`).join('')}</nav>
    <div id="tab"></div></div>`);
  const box = $('#tab', el);
  const ro = access(tab) === 'R';
  await ({ profile, organization, team, workers, cameras, zones, rules, review, delivery, notifications, privacy, audit, billing, integrations, danger })[tab](box, ro);
  if (ro) $$('input,select,textarea', box).forEach(i => { if (!i.closest('.ro-ok')) i.disabled = true; });
}

/* ---------- helpers ---------- */
const section = (title, desc, body, foot = '', cls = '') => `<div class="section ${cls}"><div class="sh"><h2>${title}</h2>${desc ? `<p>${desc}</p>` : ''}</div><div class="sb">${body}</div>${foot ? `<div class="sf">${foot}</div>` : ''}</div>`;
const row = (k, desc, v) => `<div class="set-row"><div class="k"><b>${k}</b>${desc ? `<span>${desc}</span>` : ''}</div><div class="v">${v}</div></div>`;
const sw = (path, on) => `<label class="switch"><input type="checkbox" data-k="${path}" ${on ? 'checked' : ''}><span></span></label>`;
const num = (path, val, unit, attrs = '') => `<div class="unit"><input type="number" data-k="${path}" value="${val}" ${attrs}><span>${unit}</span></div>`;
const saveFoot = (sec, note = '') => isManager() ? `${note ? `<span class="note">${note}</span>` : ''}<button class="btn ghost" data-reset="${sec}">Reset to defaults</button><button class="btn primary" data-save="${sec}">${t('save')}</button>` : '';
function collect(scope) {
  const out = {};
  $$('[data-k]', scope).forEach(i => {
    const path = i.dataset.k.split('.');
    let v = i.type === 'checkbox' ? i.checked : i.type === 'number' ? +i.value : i.value;
    if (i.dataset.scale) v = v * +i.dataset.scale;
    let o = out; path.slice(0, -1).forEach(p => o = o[p] ??= {}); o[path.at(-1)] = v;
  });
  return out;
}
function wireSave(box, transform = x => x, after = null) {
  $$('[data-save]', box).forEach(b => b.onclick = async () => {
    const sec = b.dataset.save;
    try { await api(`/api/settings/${sec}`, { method: 'PUT', body: { values: transform(collect(b.closest('.section'))) } }); toast('Saved'); await refreshMe(); after ? after() : settingsPage(sec === 'quiet_hours' ? 'notifications' : currentTab()); }
    catch (e) { fail(e); }
  });
  $$('[data-reset]', box).forEach(b => b.onclick = async () => {
    if (!await confirmBox('Reset to defaults?', 'This section goes back to WorkWatch defaults.', { label: 'Reset' })) return;
    await api(`/api/settings/${b.dataset.reset}/reset`, { method: 'POST' }).catch(fail); settingsPage(currentTab());
  });
}
const currentTab = () => location.hash.split('/')[2]?.split('?')[0] || 'profile';

/* 17.1 Profile */
async function profile(box) {
  const me = S.me, sessions = await api('/api/auth/sessions');
  box.innerHTML = section('Your profile', 'How you appear to your team and in the audit trail.',
    row('Name', '', `<input type="text" id="p-name" value="${esc(me.name || '')}">`) +
    row(t('language'), 'Interface language', `<select id="p-lang">${opt('en', 'English', S.lang)}${opt('hi', 'हिन्दी (Hindi)', S.lang)}</select>`) +
    row('Role', 'Set by a manager', `<span class="badge flat">${t(me.role)}</span>`) +
    row('Email', me.email ? '' : 'Add an email to sign in with a password', `<span>${esc(me.email || '—')}</span><button class="btn sm" id="p-email">${me.email ? 'Change' : 'Add'}</button>`) +
    row('Mobile', 'For OTP sign-in', `<span>${esc(me.phone || '—')}</span><button class="btn sm" id="p-phone">${me.phone ? 'Change' : 'Add'}</button>`) +
    row('Password', '', `<button class="btn sm" id="p-pw">Change password</button>`),
    `<button class="btn primary" id="p-save">${t('save')}</button>`, 'ro-ok') +
    section('Active sessions', 'Devices signed in to your account.', `<table class="t"><tbody>${sessions.map(s => `<tr><td>${esc(device(s.user_agent))}${s.current ? ' <span class="badge ok">this device</span>' : ''}</td><td class="small muted">Signed in ${fmtTs(s.created_at)}</td><td class="small muted">Active ${ago(s.last_seen)}</td></tr>`).join('')}</tbody></table>`,
      `<button class="btn" id="p-out">Sign out other devices</button>`) +
    section('Delete my account', 'Sends a data deletion request to your organization’s grievance officer (DPDP). Your access continues until it is processed.', '', `<button class="btn danger" id="p-del">Request deletion</button>`);
  $('#p-save', box).onclick = async () => {
    try {
      await api('/api/auth/profile', { method: 'PATCH', body: { name: $('#p-name', box).value, language: $('#p-lang', box).value } });
      S.lang = $('#p-lang', box).value; localStorage.setItem('ww_lang', S.lang); await refreshMe(); toast('Profile saved'); settingsPage('profile');
    } catch (e) { fail(e); }
  };
  $('#p-email', box).onclick = () => formModal('Change email', field('New email', '<input type="email" name="email" required>') + (me.methods?.includes('password') ? field('Current password', '<input type="password" name="password" required>') : ''),
    async fd => { await api('/api/auth/profile', { method: 'PATCH', body: Object.fromEntries(fd) }); await refreshMe(); settingsPage('profile'); });
  $('#p-phone', box).onclick = () => {
    const m = formModal('Change mobile number', field('Mobile number', '<input type="tel" name="phone" required>') + `<button type="button" class="btn sm" id="snd">Send code</button><div style="height:12px"></div>` + field('Code', '<input type="text" name="code" inputmode="numeric" maxlength="6" required>'),
      async fd => { await api('/api/auth/profile', { method: 'PATCH', body: Object.fromEntries(fd) }); await refreshMe(); settingsPage('profile'); }, { label: 'Verify & save' });
    $('#snd', m).onclick = async () => { try { const r = await api('/api/auth/otp/send', { method: 'POST', body: { phone: $('[name=phone]', m).value } }); toast(r.dev ? 'SMS not configured — code written to the server log' : 'Code sent'); } catch (e) { fail(e); } };
  };
  $('#p-pw', box).onclick = () => formModal('Change password', (me.methods?.includes('password') ? field('Current password', '<input type="password" name="password" required>') : '') + field('New password', '<input type="password" name="new_password" minlength="8" required>'),
    async fd => { await api('/api/auth/profile', { method: 'PATCH', body: Object.fromEntries(fd) }); toast('Password changed'); });
  $('#p-out', box).onclick = async () => { await api('/api/auth/sessions/signout-all', { method: 'POST' }).catch(fail); toast('Other devices signed out'); settingsPage('profile'); };
  $('#p-del', box).onclick = async () => { if (await confirmBox('Request account deletion?', 'Your organization’s grievance officer receives the request.', { label: 'Send request', danger: true })) { await api('/api/auth/delete-request', { method: 'POST' }).catch(fail); toast('Deletion request sent'); } };
}
const device = ua => !ua ? 'Unknown device' : `${/Mobile|Android|iPhone/.test(ua) ? 'Phone' : 'Computer'} · ${(ua.match(/(Edg|Chrome|Firefox|Safari)\/[\d.]+/) || ['Browser'])[0].split('/')[0].replace('Edg', 'Edge')}`;

/* 17.2 Organization */
async function organization(box) {
  const o = await api('/api/org');
  box.innerHTML = section('Company', 'Shown on reports, PDFs and GST invoices.',
    row('Logo', 'PNG or JPG, under 300 KB. Appears on PDF reports.', `${o.logo ? `<img src="${esc(o.logo)}" style="height:36px;border-radius:6px;background:#fff;padding:3px">` : ''}<label class="btn sm">${icon('upload')}Upload<input type="file" id="logo" accept="image/png,image/jpeg" hidden></label>`) +
    row('Company name', '', `<input type="text" data-o="name" value="${esc(o.name)}">`) +
    row('Industry', '', `<select data-o="industry">${['', 'Manufacturing', 'Warehousing & logistics', 'Food processing', 'Textiles & garments', 'Retail', 'Restaurants & kitchens', 'Construction', 'Other'].map(x => opt(x, x || '—', o.industry)).join('')}</select>`) +
    row('Address', '', `<textarea data-o="address" style="min-height:60px">${esc(o.address || '')}</textarea>`) +
    row('GSTIN', '15-character GST number for tax invoices', `<input type="text" data-o="gstin" value="${esc(o.gstin || '')}" maxlength="15" placeholder="29ABCDE1234F1Z5" style="text-transform:uppercase">`) +
    row('PAN', '', `<input type="text" data-o="pan" value="${esc(o.pan || '')}" maxlength="10" style="text-transform:uppercase">`) +
    row('Billing address', 'If different from the company address', `<textarea data-o="billing_address" style="min-height:60px">${esc(o.billing_address || '')}</textarea>`),
    `<button class="btn primary" id="o-save">${t('save')}</button>`) +
    section('Regional', 'Reports and the dashboard use this timezone.',
      row('Timezone', '', `<select data-o="timezone">${['Asia/Kolkata', 'Asia/Dubai', 'Asia/Singapore', 'Europe/London', 'UTC'].map(z => opt(z, z === 'Asia/Kolkata' ? 'India (IST, UTC+5:30)' : z, o.timezone)).join('')}</select>`) +
      row('Date format', '', `<select data-o="date_format">${['DD-MM-YYYY', 'DD/MM/YYYY', 'YYYY-MM-DD'].map(f => opt(f, f, o.date_format)).join('')}</select>`) +
      row('Week starts on', 'Used by weekly summaries', `<select data-o="week_start">${['Monday', 'Sunday'].map(f => opt(f, f, o.week_start)).join('')}</select>`) +
      row('Data region', 'Where footage and analysis are stored', `<span class="badge info">${icon('globe', 'ic12')} ${esc(o.data_region)}</span>`),
      `<button class="btn primary" id="o-save2">${t('save')}</button>`) +
    section('Sites', 'Factories, warehouses or branches. Assign cameras, workers and team members to sites.',
      `<table class="t"><thead><tr><th>Site</th><th>Weekly off</th><th>Holidays</th><th></th></tr></thead><tbody>${o.sites.map(s => `<tr style="${s.archived ? 'opacity:.5' : ''}"><td>${esc(s.name)}${s.archived ? ' <span class="badge flat">archived</span>' : ''}</td><td class="small">${esc(s.weekly_off.join(', ') || '—')}</td><td class="small">${s.holidays.length} date(s)</td>
        <td class="n"><button class="btn xs ghost" data-site="${s.id}">${icon('pencil')}</button></td></tr>`).join('')}</tbody></table>`,
      `<button class="btn" id="add-site">${icon('plus')}Add site</button>`);
  const save = async () => {
    const body = Object.fromEntries($$('[data-o]', box).map(i => [i.dataset.o, i.dataset.o === 'gstin' || i.dataset.o === 'pan' ? i.value.toUpperCase() : i.value]));
    if (!body.gstin) delete body.gstin;
    try { await api('/api/org', { method: 'PATCH', body }); await refreshMe(); toast('Organization saved'); settingsPage('organization'); } catch (e) { fail(e); }
  };
  $('#o-save', box).onclick = save; $('#o-save2', box).onclick = save;
  $('#logo', box).onchange = e => {
    const f = e.target.files[0]; if (!f) return;
    if (f.size > 300_000) return fail(new Error('Logo must be under 300 KB'));
    const r = new FileReader(); r.onload = async () => { await api('/api/org', { method: 'PATCH', body: { logo: r.result } }).catch(fail); settingsPage('organization'); }; r.readAsDataURL(f);
  };
  $('#add-site', box).onclick = () => formModal('Add site', field('Site name', '<input type="text" name="name" required placeholder="Plant 2 — Hosur">'), async fd => { await api('/api/sites', { method: 'POST', body: Object.fromEntries(fd) }); await refreshMe(); settingsPage('organization'); });
  const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  $$('[data-site]', box).forEach(b => b.onclick = () => {
    const s = o.sites.find(x => x.id === +b.dataset.site);
    formModal(`Edit ${s.name}`, field('Name', `<input type="text" name="name" value="${esc(s.name)}" required>`) +
      `<div class="field"><label>Weekly off</label><div class="row">${DAYS.map(d => `<label class="check" style="margin:0"><input type="checkbox" name="off" value="${d}" ${s.weekly_off.includes(d) ? 'checked' : ''}>${d.slice(0, 3)}</label>`).join('')}</div></div>` +
      field('Holidays', `<textarea name="holidays" placeholder="2026-11-08, 2026-12-25">${esc(s.holidays.join(', '))}</textarea>`, 'Dates (YYYY-MM-DD), comma separated. Excluded from expected working days.') +
      `<label class="check"><input type="checkbox" name="archived" ${s.archived ? 'checked' : ''}> Archived</label>`,
      async fd => {
        await api(`/api/sites/${s.id}`, { method: 'PATCH', body: { name: fd.get('name'), weekly_off: fd.getAll('off'), archived: !!fd.get('archived'),
          holidays: (fd.get('holidays') || '').split(/[,\s]+/).filter(x => /^\d{4}-\d{2}-\d{2}$/.test(x)) } });
        await refreshMe(); settingsPage('organization');
      }, { size: 'mid' });
  });
}

/* 17.3 Team & access */
async function team(box, ro) {
  const tm = await api('/api/team');
  const siteName = ids => ids.length ? ids.map(i => S.me.sites.find(s => s.id === i)?.name || `#${i}`).join(', ') : 'All sites';
  const M = [['Upload footage, draw zones, annotate people', 'W', '-'], ['Review queue: approve / reclassify / note', 'W', SET.review?.reviewers_can_clear ? 'W' : '-'], ['Generate & send reports', 'W', '-'],
    ['Download reports', 'W', 'W'], ['Dashboard & timelines', 'R', 'R'], ...TABS.map(([, l, , a]) => [`Settings · ${l}`, a.manager, a.reviewer])];
  const cell = x => x === 'W' ? `<span class="yes">${icon('check', 'ic12')} Change</span>` : x === 'R' ? `<span class="ro">${icon('eye', 'ic12')} View</span>` : '<span class="no">—</span>';
  box.innerHTML = section('Members', `${tm.users.length} member(s). Managers run the workspace; reviewers clear the review queue.`,
    `<div class="table-wrap"><table class="t"><thead><tr><th>Member</th><th>Role</th><th>Sites</th><th>Last active</th>${ro ? '' : '<th></th>'}</tr></thead><tbody>${tm.users.map(u => `<tr><td><div class="person-cell"><span class="avatar" style="width:28px;height:28px;font-size:11px">${esc((u.name || u.email || '?').slice(0, 2).toUpperCase())}</span><div><div class="nm">${esc(u.name)}${u.id === S.me.id ? ' <span class="faint small">(you)</span>' : ''}</div><div class="sub">${esc(u.email || u.phone || '')}</div></div></div></td>
      <td>${ro || u.id === S.me.id ? `<span class="badge flat">${t(u.role)}</span>` : `<select class="sm" data-role="${u.id}" style="width:auto">${opt('manager', t('manager'), u.role)}${opt('reviewer', t('reviewer'), u.role)}</select>`}</td>
      <td class="small">${esc(siteName(u.site_ids))}${ro ? '' : ` <button class="btn xs ghost" data-sites="${u.id}">${icon('pencil')}</button>`}</td><td class="small muted">${ago(u.last_active)}</td>
      ${ro ? '' : `<td class="n">${u.id !== S.me.id ? `<button class="btn xs ghost danger" data-rm="${u.id}">Remove</button>` : ''}</td>`}</tr>`).join('')}</tbody></table></div>`,
    ro ? '' : `<button class="btn primary" id="inv">${icon('mail')}Invite member</button>`) +
    (tm.invites.length ? section('Pending invites', 'Invite links work once. Share them on WhatsApp or email.', `<table class="t"><tbody>${tm.invites.map(i => `<tr><td>${esc(i.email)}</td><td><span class="badge flat">${t(i.role)}</span></td><td class="small muted">${ago(i.created_at)}</td>
      <td class="n"><button class="btn xs" data-copy="${esc(i.link)}">${icon('link')}Copy link</button><button class="btn xs ghost danger" data-revoke="${esc(i.token)}">Revoke</button></td></tr>`).join('')}</tbody></table>`) : '') +
    section('Access matrix', 'What each role can see and change (spec §17.16).', `<div class="table-wrap"><table class="t matrix"><thead><tr><th>Capability</th><th>${t('manager')}</th><th>${t('reviewer')}</th></tr></thead><tbody>${M.map(([l, a, b]) => `<tr><td>${esc(l)}</td><td>${cell(a)}</td><td>${cell(b)}</td></tr>`).join('')}</tbody></table></div>`);
  const re = () => settingsPage('team');
  $('#inv', box)?.addEventListener('click', () => formModal('Invite member', field('Email', '<input type="email" name="email" required placeholder="colleague@company.com">') +
    field('Role', `<select name="role">${opt('reviewer', `${t('reviewer')} — clears the review queue`)}${opt('manager', `${t('manager')} — full access`)}</select>`) +
    (S.me.sites.length > 1 ? `<div class="field"><label>Sites</label>${S.me.sites.map(s => `<label class="check"><input type="checkbox" name="site" value="${s.id}">${esc(s.name)}</label>`).join('')}<span class="hint">None selected = all sites</span></div>` : ''),
    async fd => {
      const r = await api('/api/team/invites', { method: 'POST', body: { email: fd.get('email'), role: fd.get('role'), site_ids: fd.getAll('site').map(Number) } });
      modal(`<h3>Invite created</h3><p class="muted small">${r.emailed ? 'An email with this link was sent.' : 'Email is not configured on this server — share this link yourself (WhatsApp works well).'}</p><pre>${esc(r.link)}</pre>
        <div class="mfoot"><button class="btn" id="cp">${icon('copy')}Copy link</button><button class="btn primary" data-close>Done</button></div>`, { size: 'narrow' });
      $('#cp').onclick = () => copyText(r.link); re();
    }));
  $$('[data-role]', box).forEach(s => s.onchange = async () => { try { await api(`/api/team/${s.dataset.role}`, { method: 'PATCH', body: { role: s.value } }); toast('Role updated'); } catch (e) { fail(e); re(); } });
  $$('[data-rm]', box).forEach(b => b.onclick = async () => { if (await confirmBox('Remove member?', 'They are signed out everywhere. Their past actions stay in the audit trail.', { label: 'Remove', danger: true })) { await api(`/api/team/${b.dataset.rm}`, { method: 'DELETE' }).catch(fail); re(); } });
  $$('[data-copy]', box).forEach(b => b.onclick = () => copyText(b.dataset.copy));
  $$('[data-revoke]', box).forEach(b => b.onclick = async () => { await api(`/api/team/invites/${b.dataset.revoke}`, { method: 'DELETE' }).catch(fail); re(); });
  $$('[data-sites]', box).forEach(b => b.onclick = () => {
    const u = tm.users.find(x => x.id === +b.dataset.sites);
    formModal(`Sites for ${u.name}`, `${S.me.sites.map(s => `<label class="check"><input type="checkbox" name="site" value="${s.id}" ${u.site_ids.includes(s.id) ? 'checked' : ''}>${esc(s.name)}</label>`).join('')}<p class="faint small">None selected = all sites.</p>`,
      async fd => { await api(`/api/team/${u.id}`, { method: 'PATCH', body: { site_ids: fd.getAll('site').map(Number) } }); re(); });
  });
}

/* 17.4 / 17.5 */
async function workers(box) { box.innerHTML = '<div class="row" id="wa" style="justify-content:flex-end;margin-bottom:12px"></div><div id="wb"></div>'; await renderWorkers($('#wb', box), $('#wa', box)); }
async function cameras(box) { box.innerHTML = '<div class="row" id="ca" style="justify-content:flex-end;margin-bottom:12px"></div><div id="cb"></div>'; await renderCameras($('#cb', box), $('#ca', box)); }

/* 17.6 Zone templates */
async function zones(box) {
  const cams = await api('/api/cameras');
  const Z = { work: 'Work', break: 'Break', exclusion: 'Exclusion' };
  box.innerHTML = section('Zone templates', 'Each camera’s zones are copied onto every new slice it sends. Edit a template from the camera card, or tick “Save as zone template” while drawing zones on a video.',
    cams.length ? `<table class="t"><thead><tr><th>Camera</th><th>Zones</th><th></th></tr></thead><tbody>${cams.map(c => `<tr><td>${esc(c.name)}</td><td>${c.zones.length ? c.zones.map(z => `<span class="badge flat" style="margin:2px"><span class="dot" style="background:${z.type === 'work' ? '#eeb23e' : z.type === 'break' ? '#5b8def' : '#e5534b'}"></span>${esc(z.name)} · ${Z[z.type]}</span>`).join('') : '<span class="faint small">No template</span>'}</td>
      <td class="n"><a class="btn xs" href="#/cameras">${icon('map')}Edit on Cameras</a></td></tr>`).join('')}</tbody></table>` : empty('map', 'Add a camera first.'));
}

/* 17.7 Analysis rules */
async function rules(box) {
  const r = SET.rules;
  box.innerHTML = section('Five-state rules', 'How tracked time becomes Working, Idle, Talking on phone, Break or Exclusion. Saving re-classifies all footage instantly — no re-analysis needed.',
    row('Idle threshold', 'In a work zone with no movement for longer than this → Idle', num('idle_threshold_s', r.idle_threshold_s / 60, 'minutes', 'min="0.25" step="0.25" data-scale="60"')) +
    row('Phone call threshold', 'Phone held to the ear (pose-assisted) continuously for at least this long', num('phone_threshold_s', r.phone_threshold_s, 'seconds', 'min="5" max="600"')) +
    row('Phone gap tolerance', 'Short gaps (phone hidden, looked away) bridged within one call', num('phone_gap_s', r.phone_gap_s, 'seconds', 'min="0" max="30" step="0.5"')) +
    row('Outside every zone', 'Time spent outside all drawn zones counts as', `<select data-k="outside_zone_state" style="max-width:200px">${['idle', 'break', 'exclusion', 'working'].map(s => opt(s, stateLabel(s), r.outside_zone_state)).join('')}</select>`) +
    row('Movement sensitivity', 'Lower = small movements (hand work) count as activity', num('motion_threshold', r.motion_threshold, 'pixel change', 'min="0.001" max="0.2" step="0.001"')),
    saveFoot('rules', 'Re-classifies every clip')) +
    section('Flagging for review', 'Segments matching any of these go to the review queue.',
      row('Low confidence', 'Flag segments with model confidence below', num('review_conf', Math.round(r.review_conf * 100), '%', 'min="0" max="100" data-scale="0.01"')) +
      row('Short segment', 'Flag state changes shorter than', num('min_segment_s', r.min_segment_s, 'seconds', 'min="0" max="60"')) +
      row('Short-lived track', 'Flag people seen for less than (often visitors or reflections)', num('short_track_s', r.short_track_s, 'seconds', 'min="0" max="120"')),
      saveFoot('rules')) +
    section('State labels', 'Rename states to match your floor’s language. Reports and the dashboard use these.',
      STATES.map(s => row(`<span class="dot" style="background:${STATE_COLOR[s]};margin-right:6px"></span>${t(`state.${s}`)}`, '', `<input type="text" data-k="labels.${s}" value="${esc(r.labels?.[s] || '')}">`)).join(''), saveFoot('rules'));
  // number inputs that carry a display scale (minutes / percent) — read them back in base units
  $$('[data-scale]', box).forEach(i => { i.value = +(+i.value).toFixed(3); });
  wireSave(box);
}

/* 17.8 Review preferences */
async function review(box) {
  const r = SET.review;
  box.innerHTML = section('Review preferences', '',
    row('Who is notified', 'When new items reach the queue', `<label class="check" style="margin:0"><input type="checkbox" data-n="manager" ${r.notify.includes('manager') ? 'checked' : ''}>${t('manager')}s</label><label class="check" style="margin:0"><input type="checkbox" data-n="reviewer" ${r.notify.includes('reviewer') ? 'checked' : ''}>${t('reviewer')}s</label>`) +
    row('Reminder', 'Remind again while items stay pending', num('reminder_hours', r.reminder_hours, 'hours (0 = off)', 'min="0" max="168"')) +
    row('Bulk “include similar”', 'Let one decision apply to every pending item with the same reason on a clip', sw('bulk_similar', r.bulk_similar)) +
    row('Reviewers can clear the queue', 'Off = only managers approve or reclassify (deputy reviewers)', sw('reviewers_can_clear', r.reviewers_can_clear)) +
    row('Hard gate', 'Reports cannot be generated while items are pending. This cannot be overridden.', `<span class="badge warn">${icon('lock', 'ic12')} Always on</span>`),
    saveFoot('review'));
  wireSave(box, v => ({ ...v, notify: $$('[data-n]:checked', box).map(i => i.dataset.n) }));
}

/* 17.9 Reports & delivery */
async function delivery(box) {
  const d = SET.delivery, I = SET._meta.integrations;
  const rcRow = (r = {}) => `<tr class="rc"><td><input type="text" class="sm" data-r="name" value="${esc(r.name || '')}" placeholder="Plant head"></td><td><input type="tel" class="sm" data-r="number" value="${esc(r.number || '')}" placeholder="98765 43210"></td>
    <td><select class="sm" data-r="language">${opt('en', 'English', r.language)}${opt('hi', 'Hindi', r.language)}</select></td><td><label class="switch"><input type="checkbox" data-r="opted_in" ${r.opted_in ? 'checked' : ''}><span></span></label></td><td><button class="btn xs ghost" data-rmr>${icon('x')}</button></td></tr>`;
  box.innerHTML = section('WhatsApp recipients', `${I.whatsapp ? `Sending via ${esc(I.whatsapp_provider)}.` : '<b style="color:var(--accent)">WhatsApp Business API is not configured</b> — set WHATSAPP_PROVIDER (meta, gupshup or interakt) and keys in .env.'} Only numbers that have opted in receive messages.`,
    `<table class="t"><thead><tr><th>Name</th><th>WhatsApp number</th><th>Language</th><th>Opted in</th><th></th></tr></thead><tbody id="rcs">${d.whatsapp_recipients.map(rcRow).join('')}</tbody></table><button class="btn sm" id="addrc" style="margin-top:10px">${icon('plus')}Add recipient</button>`,
    `${I.whatsapp ? '<button class="btn" data-test="whatsapp">Send test</button>' : ''}<button class="btn primary" data-save="delivery">${t('save')}</button>`) +
    section('Email recipients', I.email ? 'Reports go to these addresses (or all managers if empty).' : '<b style="color:var(--accent)">SMTP is not configured</b> — set SMTP_HOST, SMTP_USER and SMTP_PASSWORD in .env.',
      `<textarea data-k="email_recipients" placeholder="owner@company.com, hr@company.com" style="min-height:60px">${esc(d.email_recipients.join(', '))}</textarea>`,
      `${I.email ? '<button class="btn" data-test="email">Send test</button>' : ''}<button class="btn primary" data-save="delivery">${t('save')}</button>`) +
    section('Schedule & format', '',
      row('Send when a report is generated', '', sw('on_ready', d.on_ready)) + row('Daily report', 'Sent after the day’s footage is reviewed', sw('daily', d.daily)) + row('Weekly summary', 'Monday morning, last 7 days', sw('weekly', d.weekly)) +
      row('Attachments', '', ['xlsx', 'pdf', 'csv'].map(f => `<label class="check" style="margin:0"><input type="checkbox" data-fmt="${f}" ${d.formats.includes(f) ? 'checked' : ''}>${{ xlsx: 'Excel', pdf: 'PDF', csv: 'CSV' }[f]}</label>`).join('')) +
      row('Zone breakdown', 'Include time per zone', sw('zone_breakdown', d.zone_breakdown)) + row('Show formulas', 'Explain efficiency and thresholds in the report', sw('show_formula', d.show_formula)) +
      row('Default payroll format', '', `<select data-k="payroll_format" style="max-width:200px">${['greytHR', 'Keka', 'Zoho Payroll', 'Tally'].map(f => opt(f, f, d.payroll_format)).join('')}</select>`) +
      row('PDF footer', 'e.g. “Confidential — for payroll use only”', `<input type="text" data-k="pdf_footer" value="${esc(d.pdf_footer)}">`),
      saveFoot('delivery'));
  $('#addrc', box).onclick = () => { $('#rcs', box).insertAdjacentHTML('beforeend', rcRow({ opted_in: true })); wireRm(); };
  const wireRm = () => $$('[data-rmr]', box).forEach(b => b.onclick = () => b.closest('tr').remove());
  wireRm();
  const collectAll = () => ({
    ...collect(box), email_recipients: $('[data-k=email_recipients]', box).value.split(/[,\s]+/).filter(x => x.includes('@')),
    formats: $$('[data-fmt]:checked', box).map(i => i.dataset.fmt),
    whatsapp_recipients: $$('.rc', box).map(r => Object.fromEntries($$('[data-r]', r).map(i => [i.dataset.r, i.type === 'checkbox' ? i.checked : i.value]))).filter(r => r.number),
  });
  $$('[data-save]', box).forEach(b => b.onclick = async () => { try { await api('/api/settings/delivery', { method: 'PUT', body: { values: collectAll() } }); toast('Delivery settings saved'); settingsPage('delivery'); } catch (e) { fail(e); } });
  $$('[data-reset]', box).forEach(b => b.onclick = async () => { await api('/api/settings/delivery/reset', { method: 'POST' }).catch(fail); settingsPage('delivery'); });
  $$('[data-test]', box).forEach(b => b.onclick = () => formModal(`Send a test ${b.dataset.test === 'email' ? 'email' : 'WhatsApp message'}`, field('To', `<input type="text" name="to" value="${esc(b.dataset.test === 'email' ? S.me.email || '' : '')}" required>`),
    async fd => { await api(`/api/settings/test/${b.dataset.test}`, { method: 'POST', body: { to: fd.get('to') } }); toast('Test sent'); }, { label: 'Send' }));
}

/* 17.10 Notifications */
async function notifications(box) {
  const n = SET.notifications, q = SET.quiet_hours, ev = SET._meta.events, I = SET._meta.integrations;
  box.innerHTML = section('Events', 'Choose how your organization hears about each event. Email and WhatsApp go to the recipients in Reports & delivery.',
    `<div class="table-wrap"><table class="t matrix"><thead><tr><th>Event</th><th>In-app</th><th>Email${I.email ? '' : ' <span class="faint">(off)</span>'}</th><th>WhatsApp${I.whatsapp ? '' : ' <span class="faint">(off)</span>'}</th></tr></thead><tbody>
    ${Object.entries(ev).map(([k, l]) => `<tr><td>${esc(l)}</td>${['in_app', 'email', 'whatsapp'].map(ch => `<td>${sw(`${k}.${ch}`, n[k]?.[ch])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`, saveFoot('notifications')) +
    section('Quiet hours', 'No email or WhatsApp in this window (in-app notifications still arrive). IST.',
      row('Enabled', '', sw('enabled', q.enabled)) + row('From', '', `<input type="time" data-k="start" value="${esc(q.start)}" style="max-width:140px">`) + row('Until', '', `<input type="time" data-k="end" value="${esc(q.end)}" style="max-width:140px">`),
      saveFoot('quiet_hours'));
  wireSave(box);
}

/* 17.11 Privacy & consent (DPDP) */
async function privacy(box, ro) {
  const p = SET.privacy, region = SET._meta.data_region;
  const reqs = ro ? [] : await api('/api/privacy/requests');
  box.innerHTML = section('Footage', '',
    row('Face blur', 'Blur heads in every frame, thumbnail and playback shown in WorkWatch', sw('face_blur', p.face_blur)) +
    row('Retention', 'Raw footage is deleted after this; analysis and reports are kept', `<select data-k="retention_days" style="max-width:160px">${[30, 60, 90].map(d => opt(d, `${d} days`, p.retention_days)).join('')}</select>`) +
    row('Data region', '', `<span class="badge info">${icon('globe', 'ic12')} ${esc(region)}</span>`) +
    row('Face recognition', 'WorkWatch never identifies people by face — you name tracks yourself', '<span class="badge ok">Never used</span>'),
    saveFoot('privacy')) +
    section('Notices (DPDP Act 2023)', p.notice_issued_on ? `Awareness notice marked as issued on ${fmtDay(p.notice_issued_on)}.` : '<b style="color:var(--accent)">Not issued yet.</b> Print the notice, display it at the site and share it with workers, then mark it issued.',
      field('Consent / purpose notice', `<textarea data-k="consent_text" style="min-height:100px">${esc(p.consent_text)}</textarea>`) +
      field('Employee awareness notice', `<textarea data-k="awareness_text" style="min-height:100px">${esc(p.awareness_text)}</textarea>`) +
      `<div class="grid g-2" style="gap:12px">${field('Grievance officer', `<input type="text" data-k="grievance_name" value="${esc(p.grievance_name)}" placeholder="Name and designation">`)}${field('Grievance contact', `<input type="text" data-k="grievance_contact" value="${esc(p.grievance_contact)}" placeholder="email or phone">`)}</div>`,
      `${ro ? '' : `<button class="btn" id="print">${icon('printer')}Print notice</button><button class="btn" id="issued">${icon('check')}Mark issued today</button>`}<button class="btn primary" data-save="privacy" ${ro ? 'hidden' : ''}>${t('save')}</button>`) +
    (ro ? '' : section('Data requests', 'Access, correction and deletion requests from workers or team members. Track them to closure.',
      reqs.length ? `<table class="t"><thead><tr><th>Who</th><th>Contact</th><th>Details</th><th>Received</th><th>Status</th></tr></thead><tbody>${reqs.map(r => `<tr><td>${esc(r.subject)}</td><td class="small">${esc(r.contact || '—')}</td><td class="small">${esc(r.details || '')}${r.resolution ? `<div class="faint">→ ${esc(r.resolution)}</div>` : ''}</td><td class="small muted">${fmtTs(r.created_at)}</td>
        <td><select class="sm" data-req="${r.id}" style="width:auto">${['open', 'in_progress', 'completed', 'rejected'].map(s => opt(s, s.replace('_', ' '), r.status)).join('')}</select></td></tr>`).join('')}</tbody></table>` : '<p class="muted small" style="margin:0">No requests.</p>',
      `<a class="btn" href="/api/privacy/export">${icon('download')}Export all data (JSON)</a><button class="btn primary" id="addreq">${icon('plus')}Log a request</button>`));
  wireSave(box);
  $('#issued', box)?.addEventListener('click', async () => { await api('/api/privacy/notice-issued', { method: 'POST' }).catch(fail); await refreshMe(); toast('Notice marked as issued'); settingsPage('privacy'); });
  $('#print', box)?.addEventListener('click', () => {
    const w = open('', '_blank');
    w.document.write(`<html><head><title>CCTV analytics notice</title><style>body{font-family:system-ui,sans-serif;max-width:720px;margin:40px auto;line-height:1.6;color:#111}h1{font-size:22px}h2{font-size:16px;margin-top:28px}</style></head><body>
      <h1>${esc(S.me.org.name)} — CCTV video analytics notice</h1><h2>Purpose</h2><p>${esc($('[data-k=consent_text]', box).value)}</p><h2>Notice to employees</h2><p>${esc($('[data-k=awareness_text]', box).value)}</p>
      <h2>Retention</h2><p>Raw footage is deleted after ${p.retention_days} days. ${p.face_blur ? 'Faces are blurred in all views.' : ''} No face recognition is used.</p>
      <h2>Grievance officer</h2><p>${esc($('[data-k=grievance_name]', box).value || '—')}<br>${esc($('[data-k=grievance_contact]', box).value || '')}</p><p style="color:#666;font-size:12px">Issued ${new Date().toLocaleDateString('en-IN')}</p></body></html>`);
    w.document.close(); w.print();
  });
  $$('[data-req]', box).forEach(s => s.onchange = async () => {
    const resolution = ['completed', 'rejected'].includes(s.value) ? prompt('Resolution note (sent to the audit trail):') || '' : undefined;
    await api(`/api/privacy/requests/${s.dataset.req}`, { method: 'PATCH', body: { status: s.value, resolution } }).catch(fail); settingsPage('privacy');
  });
  $('#addreq', box)?.addEventListener('click', () => formModal('Log a data request', field('Who is it about?', '<input type="text" name="subject" required placeholder="Worker name">') + field('Contact', '<input type="text" name="contact">') +
    field('Request', '<textarea name="details" placeholder="e.g. Delete footage from 12 Oct; correct phone time on 14 Oct"></textarea>'),
    async fd => { await api('/api/privacy/requests', { method: 'POST', body: Object.fromEntries(fd) }); settingsPage('privacy'); }));
}

/* 17.12 Audit trail */
async function audit(box) {
  const q = new URLSearchParams(location.hash.split('?')[1] || '');
  const items = await api(`/api/audit?${new URLSearchParams({ q: q.get('q') || '', action: q.get('action') || '' })}`);
  const groups = ['', 'review', 'annotation', 'zones', 'report', 'settings', 'team', 'video', 'camera', 'privacy', 'billing', 'danger'];
  box.innerHTML = section('Audit trail', 'Every change, who made it and what it was before. Entries are immutable — they cannot be edited or deleted, even by managers.',
    `<div class="filters" style="margin-bottom:14px">${field('Search', `<input type="search" id="aq" value="${esc(q.get('q') || '')}" placeholder="user, action or value">`)}
      ${field('Area', `<select id="aa">${groups.map(g => opt(g, g || 'Everything', q.get('action'))).join('')}</select>`)}</div>
    ${items.length ? `<div class="table-wrap" style="max-height:640px;overflow:auto"><table class="t"><thead><tr><th>When (IST)</th><th>Who</th><th>Action</th><th>Change</th></tr></thead><tbody>
      ${items.map(a => `<tr><td class="small muted" style="white-space:nowrap">${fmtTs(a.created_at)}</td><td class="small">${esc(a.user_label)}</td><td><code>${esc(a.action)}</code>${a.entity ? `<div class="small faint">${esc(a.entity)} ${esc(a.entity_id || '')}</div>` : ''}</td>
        <td class="small" style="max-width:420px">${diff(a.before, a.after)}</td></tr>`).join('')}</tbody></table></div>` : empty('history', 'No matching entries.')}`,
    `<a class="btn" href="/api/audit?fmt=csv&${new URLSearchParams({ q: q.get('q') || '', action: q.get('action') || '' })}">${icon('download')}Export CSV</a>`);
  const go = () => { location.hash = `#/settings/audit?${new URLSearchParams({ q: $('#aq', box).value, action: $('#aa', box).value })}`; };
  $('#aq', box).onchange = go; $('#aa', box).onchange = go;
}
function diff(b, a) {
  const short = v => { const s = typeof v === 'object' ? JSON.stringify(v) : String(v); return esc(s.length > 70 ? s.slice(0, 70) + '…' : s); };
  if (b && a && typeof b === 'object' && typeof a === 'object' && !Array.isArray(a)) {
    const keys = [...new Set([...Object.keys(b), ...Object.keys(a)])].filter(k => JSON.stringify(b[k]) !== JSON.stringify(a[k])).slice(0, 4);
    if (keys.length) return keys.map(k => `<div><b style="font-weight:500">${esc(k)}</b>: <span class="faint">${short(b[k] ?? '—')}</span> → ${short(a[k] ?? '—')}</div>`).join('');
  }
  return a ? short(a) : b ? `<span class="faint">removed ${short(b)}</span>` : '';
}

/* 17.13 Billing & usage */
async function billing(box) {
  const b = await api('/api/billing');
  const meter = (l, used, lim, unit) => `<div style="margin-bottom:14px"><div class="row small"><span>${l}</span><span class="spacer"></span><span class="muted">${used} / ${lim} ${unit}</span></div><div class="meter ${used / lim > 0.9 ? 'hot' : ''}" style="margin-top:6px"><div style="width:${Math.min(100, 100 * used / lim)}%"></div></div></div>`;
  const trial = b.plan === 'trial' ? Math.max(0, Math.ceil((b.trial_ends - Date.now() / 1000) / 86400)) : null;
  box.innerHTML = section('Usage this month', `${b.usage.period} · ${trial != null ? `Trial with Growth limits — ${trial} day(s) left` : `${b.plans[b.plan]?.name || b.plan} plan`}`,
    meter('Analysed footage', b.usage.hours, b.limits.hours, 'hours') + meter('Cameras', b.usage.cameras, b.limits.cameras, '') + meter('Team members', b.usage.users, b.limits.users, '') +
    `<p class="faint small" style="margin:0">Storage in use: ${b.usage.storage_gb} GB of footage (deleted automatically after the retention period).</p>`) +
    section('Plans', 'Prices in INR per month, billed monthly. 18% GST added on the invoice.',
      `<div class="plans">${Object.entries(b.plans).map(([k, p]) => `<div class="plan ${b.plan === k ? 'current' : ''}"><b>${esc(p.name)}</b><div class="price">${inr(p.price)}<small> /month + GST</small></div>
        <ul>${p.features.map(f => `<li>${esc(f)}</li>`).join('')}</ul>${b.plan === k ? '<span class="badge ok" style="align-self:flex-start">Current plan</span>' : `<button class="btn ${k === 'growth' ? 'primary' : ''}" data-plan="${k}">Choose ${esc(p.name)}</button>`}</div>`).join('')}</div>
      ${b.gateway.razorpay ? '' : '<div class="banner info" style="margin:14px 0 0">' + icon('info') + '<div><b>Payments are not configured.</b> Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in .env to take payments with Razorpay (UPI, cards, netbanking).</div></div>'}
      ${!b.gstin ? '<p class="faint small" style="margin:12px 0 0">Add your GSTIN in Organization settings to claim input tax credit on invoices.</p>' : ''}`) +
    section('Invoices', '', b.invoices.length ? `<table class="t"><thead><tr><th>Invoice</th><th>Period</th><th>Plan</th><th class="n">Amount</th><th class="n">GST</th><th class="n">Total</th><th>Status</th><th></th></tr></thead><tbody>
      ${b.invoices.map(i => `<tr><td>${esc(i.number)}</td><td>${esc(i.period)}</td><td>${esc(i.plan)}</td><td class="n">${inr(i.amount)}</td><td class="n">${inr(i.gst)}</td><td class="n"><b>${inr(i.total)}</b></td><td><span class="badge ${i.status === 'paid' ? 'ok' : 'warn'}">${esc(i.status)}</span></td>
        <td class="n"><a class="btn xs" href="/api/billing/invoices/${i.id}">${icon('download')}PDF</a></td></tr>`).join('')}</tbody></table>` : '<p class="muted small" style="margin:0">No invoices yet.</p>');
  $$('[data-plan]', box).forEach(btn => btn.onclick = async () => {
    try {
      const o = await api('/api/billing/checkout', { method: 'POST', body: { plan: btn.dataset.plan } });
      await loadScript('https://checkout.razorpay.com/v1/checkout.js');
      new window.Razorpay({ key: o.key_id, order_id: o.order_id, amount: o.amount, currency: 'INR', name: 'WorkWatch', description: `${b.plans[btn.dataset.plan].name} plan`,
        prefill: { email: S.me.email || '', contact: S.me.phone || '' }, theme: { color: '#eeb23e' },
        handler: async resp => { try { await api('/api/billing/verify', { method: 'POST', body: { ...resp, plan: btn.dataset.plan } }); await refreshMe(); toast('Payment received — plan upgraded'); settingsPage('billing'); } catch (e) { fail(e); } } }).open();
    } catch (e) { fail(e); }
  });
}
const loadScript = src => new Promise((res, rej) => { if ([...document.scripts].some(s => s.src === src)) return res(); const s = document.createElement('script'); s.src = src; s.onload = res; s.onerror = () => rej(new Error('Could not load the payment window')); document.head.appendChild(s); });

/* 17.14 Integrations */
async function integrations(box) {
  const I = SET._meta.integrations;
  const it = (ic, name, desc, on, env) => `<div class="integ"><span class="ic">${icon(ic)}</span><div><b style="font-weight:500">${name}</b><div class="small muted">${desc}</div>${on ? '' : `<div class="small faint" style="margin-top:3px">Set ${env} in <code>.env</code> and restart.</div>`}</div>
    ${on ? '<span class="badge ok"><span class="d"></span>Connected</span>' : '<span class="badge flat">Not configured</span>'}</div>`;
  const soon = (ic, name, desc) => `<div class="integ" style="opacity:.6"><span class="ic">${icon(ic)}</span><div><b style="font-weight:500">${name}</b><div class="small muted">${desc}</div></div><span class="badge flat">Coming in v2</span></div>`;
  box.innerHTML = section('Connected services', 'Configured by your WorkWatch administrator on the server. Nothing is simulated — unconfigured channels show as “not configured” in delivery logs.',
    it('whatsapp', `WhatsApp Business${I.whatsapp_provider ? ` · ${esc(I.whatsapp_provider)}` : ''}`, 'Daily reports and alerts via Meta Cloud API, Gupshup or Interakt.', I.whatsapp, 'WHATSAPP_PROVIDER, WHATSAPP_TOKEN') +
    it('mail', 'Email (SMTP)', 'Report attachments and invites.', I.email, 'SMTP_HOST, SMTP_USER, SMTP_PASSWORD') +
    it('phone', 'SMS OTP', 'Mobile number sign-in via MSG91 or Twilio.', I.sms, 'SMS_PROVIDER, SMS_KEY') +
    it('globe', 'Google sign-in', 'Sign in with Google Workspace accounts.', I.google, 'GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET') +
    it('card', 'Razorpay', 'Plan payments in INR with GST invoices.', I.razorpay, 'RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET') +
    it('gpu', 'Remote GPU workers', 'Cloud GPU machines that pull analysis jobs from the queue.', I.worker_token, 'WW_WORKER_TOKEN')) +
    section('Payroll & HR sync', 'Today: download greytHR, Keka, Zoho Payroll and Tally files from Reports.',
      soon('sheet', 'greytHR attendance API', 'Push approved working hours straight into attendance.') + soon('sheet', 'Keka / Zoho People', 'Two-way employee list sync.') + soon('plug', 'Webhooks', 'Send report-ready events to your own systems.'));
}

/* 17.15 Danger zone */
async function danger(box) {
  box.innerHTML = section('Delete all footage', 'Removes every video file now. Analysis, review decisions and reports are kept. Use this after an incident or before closing an account.', '',
    `<button class="btn danger" id="d-foot">${icon('trash')}Delete all footage</button>`, 'danger-zone') +
    section('Delete organization', 'Permanently deletes the organization, its team, cameras, footage, analysis and reports. This cannot be undone. The audit trail is retained for compliance.', '',
      `<button class="btn danger solid" id="d-org">${icon('trash')}Delete ${esc(S.me.org.name)}</button>`, 'danger-zone');
  $('#d-foot', box).onclick = async () => {
    const v = await confirmBox('Delete all footage?', 'Every video file is removed immediately.', { label: 'Delete footage', danger: true, typed: S.me.org.name });
    if (v) { try { const r = await api('/api/danger/delete-footage', { method: 'POST', body: { confirm: v } }); toast(`${r.deleted} file(s) deleted`); } catch (e) { fail(e); } }
  };
  $('#d-org', box).onclick = async () => {
    const v = await confirmBox('Delete organization?', 'Everything is deleted. You will be signed out.', { label: 'Delete forever', danger: true, typed: S.me.org.name });
    if (v) { try { await api('/api/danger/delete-org', { method: 'POST', body: { confirm: v } }); S.me = null; location.hash = '#/'; } catch (e) { fail(e); } }
  };
}
