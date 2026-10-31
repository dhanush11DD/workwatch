import { $, $$, S, t, esc, icon, api, toast, fail, modal, isManager, hm, hms, fmtTs, fmtDay, STATES, STATE_COLOR, stateLabel, pctBar, opt, field, empty, todayIST, download } from '../core.js';
import { mount } from '../main.js';

let F = null;
let view = 'build';

export async function reportsPage() {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  const vid = params.get('video');
  if (!F || vid) {
    const end = todayIST();
    const start = new Date(Date.parse(end) - 6 * 86400e3).toISOString().slice(0, 10);
    F = vid ? { video_ids: [+vid] } : { date_from: start, date_to: end };
  }
  const [cams, workers, reports, formats] = await Promise.all([api('/api/cameras'), api('/api/workers'), api('/api/reports'), api('/api/payroll-formats')]);
  const el = mount('reports', `<b>${t('nav.reports')}</b>`, `
    <div class="page-head"><div><h1>${t('nav.reports')}</h1><p>Per-worker working, idle, phone, break and excluded time. Generated only from reviewed footage.</p></div>
      <div class="seg">${[['build', 'Build report'], ['history', `Generated (${reports.length})`], ['log', 'Delivery log']].map(([k, l]) => `<button data-view="${k}" class="${view === k ? 'active' : ''}">${l}</button>`).join('')}</div></div>
    <div id="pane"></div>`);
  $$('[data-view]', el).forEach(b => b.onclick = () => { view = b.dataset.view; reportsPage(); });
  const pane = $('#pane', el);
  if (view === 'history') return historyPane(pane, reports, formats);
  if (view === 'log') return logPane(pane);
  buildPane(pane, cams, workers);
}

async function buildPane(pane, cams, workers) {
  const shifts = [...new Set(cams.flatMap(c => c.shifts.map(s => s.name)))];
  pane.innerHTML = `<div class="card" style="margin-bottom:20px"><div class="filters">
      ${F.video_ids ? `<div class="field"><label>Footage</label><div class="row"><span class="badge info">1 clip selected</span><button class="btn xs ghost" id="clearv">${icon('x')}Clear</button></div></div>` : `
      ${field('From', `<input type="date" data-f="date_from" value="${esc(F.date_from || '')}">`)}${field('To', `<input type="date" data-f="date_to" value="${esc(F.date_to || '')}">`)}`}
      ${S.me.sites.length > 1 ? field('Site', `<select data-f="site_id"><option value="">All sites</option>${S.me.sites.map(s => opt(s.id, s.name, F.site_id)).join('')}</select>`) : ''}
      ${field('Camera', `<select data-f="camera_id"><option value="">All cameras</option>${cams.map(c => opt(c.id, c.name, F.camera_id)).join('')}</select>`)}
      ${field('Shift', `<select data-f="shift"><option value="">All shifts</option>${shifts.map(s => opt(s, s, F.shift)).join('')}</select>`)}
      ${field('Worker', `<select data-f="worker"><option value="">All workers</option>${workers.filter(w => w.active).map(w => opt(w.name, w.name, F.worker)).join('')}</select>`)}
      <div class="field" id="zf"></div>
    </div><label class="check" style="margin:12px 0 0"><input type="checkbox" data-f="reviewed_only" ${F.reviewed_only ? 'checked' : ''}> Skip footage that isn’t fully reviewed (generate from what’s ready)</label></div>
    <div id="preview"><div class="skeleton" style="height:240px"></div></div>`;
  $$('[data-f]', pane).forEach(i => i.onchange = () => {
    const k = i.dataset.f, val = i.type === 'checkbox' ? i.checked : i.value;
    F = { ...F, [k]: val || undefined }; if (k === 'site_id' || k === 'camera_id') F[k] = val ? +val : undefined;
    preview(pane);
  });
  $('#clearv', pane)?.addEventListener('click', () => { F = null; history.replaceState(null, '', '#/reports'); reportsPage(); });
  preview(pane);
}

async function preview(pane) {
  const box = $('#preview', pane);
  let p;
  try { p = await api('/api/reports/preview', { method: 'POST', body: F }); } catch (e) { box.innerHTML = ''; return fail(e); }
  const zones = Object.keys(p.zones);
  $('#zf', pane).innerHTML = `<label>Zone</label><select data-f="zone"><option value="">All zones</option>${[...new Set([...zones, ...(F.zone ? [F.zone] : [])])].map(z => opt(z, z, F.zone)).join('')}</select>`;
  $('[data-f=zone]', pane).onchange = e => { F = { ...F, zone: e.target.value || undefined }; preview(pane); };
  const T = p.totals, blocked = p.blockers.length > 0 && !F.reviewed_only;
  const kpi = (l, v, c = '') => `<div class="kpi"><div class="lbl">${c ? `<span class="dot" style="background:${c}"></span>` : ''}${l}</div><div class="val" style="font-size:22px">${v}</div></div>`;
  box.innerHTML = `
    ${p.blockers.length ? `<div class="banner ${F.reviewed_only ? 'info' : 'err'}">${icon(F.reviewed_only ? 'info' : 'lock')}<div><b>${F.reviewed_only ? `${p.blockers.length} clip(s) skipped` : `Report blocked — ${p.blockers.length} item(s) to clear first`}</b>
      <ul>${p.blockers.slice(0, 6).map(b => `<li>${esc(b)}</li>`).join('')}${p.blockers.length > 6 ? `<li>…and ${p.blockers.length - 6} more</li>` : ''}</ul></div>${!F.reviewed_only ? '<a class="btn sm" href="#/review">Open review queue</a>' : ''}</div>` : ''}
    ${p.notes.length ? `<div class="banner info">${icon('alert')}<div><b>Notes carried into the report</b><ul>${p.notes.map(n => `<li>${esc(n)}</li>`).join('')}</ul></div></div>` : ''}
    ${p.rows.length ? `<div class="grid" style="grid-template-columns:repeat(6,minmax(0,1fr));margin-bottom:20px" id="kp">
      ${kpi('People', T.people)}${kpi(t('efficiency'), `${T.efficiency}%`)}${STATES.slice(0, 4).map(s => kpi(esc(stateLabel(s)), hm(T[`${s}_s`]), STATE_COLOR[s])).join('')}</div>
    <div class="card flush"><div class="card-head" style="padding:16px 20px 0"><h2>Preview</h2><span class="sub">${p.used.length} clip(s)</span><span class="spacer"></span>
      ${isManager() ? `<button class="btn primary" id="gen" ${blocked ? 'disabled' : ''}>${icon(blocked ? 'lock' : 'file')}${t('generate_report')}</button>` : '<span class="faint small">Managers generate reports</span>'}</div>
      <div class="table-wrap" style="margin-top:12px"><table class="t"><thead><tr><th>Person</th><th>Employee ID</th><th style="width:18%">Breakdown</th>${STATES.map(s => `<th class="n">${esc(stateLabel(s))}</th>`).join('')}<th class="n">Present</th><th class="n">Eff.</th><th class="n">Flags</th></tr></thead><tbody>
      ${p.rows.map(r => `<tr><td><b style="font-weight:500">${esc(r.person)}</b><div class="small faint">${esc(r.dates.map(fmtDay).join(', '))}</div></td><td class="muted">${esc(r.employee_id || '—')}</td>
        <td>${pctBar(Object.fromEntries(STATES.map(s => [s, r[`${s}_s`]])), r.present_s)}</td>${STATES.map(s => `<td class="n">${r[`${s}_s`] ? hms(r[`${s}_s`]) : '<span class="faint">–</span>'}</td>`).join('')}
        <td class="n">${hms(r.present_s)}</td><td class="n"><b>${r.efficiency}%</b></td><td class="n">${r.flagged || '–'}</td></tr>`).join('')}</tbody></table></div></div>
    ${zones.length ? `<div class="card flush" style="margin-top:20px"><div class="card-head" style="padding:16px 20px 0"><h2>Zone breakdown</h2></div><div class="table-wrap"><table class="t"><thead><tr><th>Zone</th>${STATES.map(s => `<th class="n">${esc(stateLabel(s))}</th>`).join('')}</tr></thead><tbody>
      ${zones.map(z => `<tr><td>${esc(z)}</td>${STATES.map(s => `<td class="n">${p.zones[z][s] ? hm(p.zones[z][s]) : '<span class="faint">–</span>'}</td>`).join('')}</tr>`).join('')}</tbody></table></div></div>` : ''}
    <p class="faint small">Efficiency = working ÷ (present − exclusion). Idle = in a work zone with no activity for longer than the idle threshold. Phone = 30 s+ continuous calls (gaps up to a few seconds bridged). Times in IST.</p>`
    : empty('file', p.blockers.length ? 'Nothing is ready to report yet.' : 'No analysed footage matches these filters.')}`;
  if (innerWidth < 900) $('#kp', box)?.style.setProperty('grid-template-columns', 'repeat(2,minmax(0,1fr))');
  $('#gen', box)?.addEventListener('click', async () => {
    try { const r = await api('/api/reports', { method: 'POST', body: F }); toast(`${r.title} generated`); view = 'history'; reportsPage(); }
    catch (e) { fail(e); preview(pane); }
  });
}

function historyPane(pane, reports, formats) {
  pane.innerHTML = reports.length ? `<div class="card flush"><div class="table-wrap"><table class="t"><thead><tr><th>Report</th><th class="n">People</th><th class="n">Working</th><th class="n">Eff.</th><th>Status</th><th>Created</th><th class="n">Download</th>${isManager() ? '<th></th>' : ''}</tr></thead><tbody>
    ${reports.map(r => `<tr><td><b style="font-weight:500">${esc(r.title)}</b>${r.notes?.length ? `<div class="small" style="color:var(--accent)">${r.notes.length} note(s) · partial footage</div>` : ''}</td>
      <td class="n">${r.totals.people}</td><td class="n">${hm(r.totals.working_s)}</td><td class="n">${r.totals.efficiency}%</td>
      <td>${r.status === 'sent' ? '<span class="badge ok"><span class="d"></span>Sent</span>' : '<span class="badge info"><span class="d"></span>Ready</span>'}
        ${r.deliveries.filter(d => d.status !== 'sent').map(d => `<span class="badge ${d.status === 'failed' ? 'err' : 'flat'}" title="${esc(d.channel)}">${esc(d.channel)}: ${esc(d.status.replace('_', ' '))}</span>`).join(' ')}</td>
      <td class="small muted">${fmtTs(r.created_at)}<div>${esc(r.created_by || '')}</div></td>
      <td class="n"><div class="btn-group"><a class="btn xs" href="/api/reports/${r.id}/export?fmt=xlsx" title="Excel">${icon('sheet')}Excel</a><a class="btn xs" href="/api/reports/${r.id}/export?fmt=pdf">PDF</a><a class="btn xs" href="/api/reports/${r.id}/export?fmt=csv">CSV</a>
        <button class="btn xs" data-pay="${r.id}" title="Payroll export">Payroll ▾</button></div></td>
      ${isManager() ? `<td class="n"><button class="btn xs primary" data-send="${r.id}">${icon('send')}Send</button></td>` : ''}</tr>`).join('')}</tbody></table></div></div>`
    : empty('file', 'No reports generated yet. Build one from reviewed footage.');
  $$('[data-pay]', pane).forEach(b => b.onclick = () => {
    const m = modal(`<h3>Payroll export</h3><p class="muted small">Attendance-import layouts. Check the columns against your account’s template before the first import.</p>
      <div class="stack">${formats.map(f => `<a class="btn block" style="justify-content:flex-start" href="/api/reports/${b.dataset.pay}/export?fmt=payroll&payroll=${encodeURIComponent(f)}">${icon('download')}${esc(f)}</a>`).join('')}</div>
      <div class="mfoot"><button class="btn" data-close>${t('close')}</button></div>`, { size: 'narrow' });
    $$('a', m).forEach(a => a.addEventListener('click', () => setTimeout(m.close, 300)));
  });
  $$('[data-send]', pane).forEach(b => b.onclick = () => {
    const m = modal(`<h3>Send report</h3><p class="muted small">Recipients come from Settings → Reports & delivery. Channels that aren’t configured are logged as “not configured” — nothing is faked.</p>
      <label class="check"><input type="checkbox" value="email" checked> ${icon('mail', 'ic12')} Email (Excel + PDF attached)</label>
      <label class="check"><input type="checkbox" value="whatsapp" checked> ${icon('whatsapp', 'ic12')} WhatsApp (summary + PDF link)</label>
      <div id="res"></div><div class="mfoot"><a class="btn ghost" href="#/settings/delivery">Recipients</a><span class="spacer"></span><button class="btn" data-close>${t('close')}</button><button class="btn primary" id="go">${icon('send')}Send now</button></div>`, { size: 'narrow' });
    $('#go', m).onclick = async () => {
      const channels = $$('input:checked', m).map(i => i.value);
      try {
        const r = await api(`/api/reports/${b.dataset.send}/deliver`, { method: 'POST', body: { channels } });
        $('#res', m).innerHTML = `<table class="t" style="margin-top:12px"><tbody>${r.results.map(x => `<tr><td>${esc(x.channel)}</td><td class="small">${esc(x.recipient)}</td><td><span class="badge ${x.status === 'sent' ? 'ok' : x.status === 'failed' ? 'err' : 'flat'}">${esc(x.status.replace('_', ' '))}</span>${x.error ? `<div class="small faint">${esc(x.error)}</div>` : ''}</td></tr>`).join('')}</tbody></table>`;
        $('#go', m).remove();
      } catch (e) { fail(e); }
    };
    m.addEventListener('closed', () => reportsPage());
  });
}

async function logPane(pane) {
  const log = await api('/api/deliveries');
  pane.innerHTML = log.length ? `<div class="card flush"><div class="table-wrap"><table class="t"><thead><tr><th>When</th><th>Report</th><th>Channel</th><th>Recipient</th><th>Status</th></tr></thead><tbody>
    ${log.map(d => `<tr><td class="small muted">${fmtTs(d.created_at)}</td><td>${esc(d.title || d.kind)}</td><td>${esc(d.channel)}</td><td class="small">${esc(d.recipient)}</td>
      <td><span class="badge ${d.status === 'sent' ? 'ok' : d.status === 'failed' ? 'err' : 'flat'}">${esc(d.status.replace('_', ' '))}</span>${d.error ? `<div class="small faint">${esc(d.error)}</div>` : ''}</td></tr>`).join('')}</tbody></table></div></div>`
    : empty('send', 'Nothing has been delivered yet.');
}
