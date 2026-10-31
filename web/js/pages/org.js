import { $, $$, S, t, esc, icon, api, toast, fail, modal, formModal, confirmBox, isManager, ago, fmtTs, opt, field, empty, copyText, onLeave } from '../core.js';
import { mount } from '../main.js';
import { Overlay, zoneTools } from '../overlay.js';

/* ---------- workers (saved list used to name tracked people) ---------- */
export async function workersPage() {
  const el = mount('workers', `<b>${t('nav.workers')}</b>`, `<div class="page-head"><div><h1>${t('nav.workers')}</h1><p>Your saved worker list. Name tracked people from it so reports line up with payroll employee IDs.</p></div><div class="actions" id="wact"></div></div><div id="wbox"></div>`);
  await renderWorkers($('#wbox', el), $('#wact', el));
}

export async function renderWorkers(box, actions = box) {
  const ws = await api('/api/workers');
  const mgr = isManager();
  if (mgr) {
    const bar = document.createElement('div'); bar.className = 'row';
    bar.innerHTML = `<label class="btn">${icon('upload')}Import CSV<input type="file" accept=".csv" hidden id="wcsv"></label><button class="btn primary" id="wadd">${icon('plus')}Add worker</button>`;
    actions === box ? box.before(bar) : actions.replaceChildren(bar);
    $('#wadd', bar).onclick = () => editWorker(null, () => renderWorkers(box, actions));
    $('#wcsv', bar).onchange = async e => {
      const fd = new FormData(); fd.append('file', e.target.files[0]);
      try { const r = await api('/api/workers/import', { method: 'POST', body: fd }); toast(`${r.added} added, ${r.skipped} skipped (duplicates or blank)`); renderWorkers(box, actions); } catch (er) { fail(er); }
    };
  }
  box.innerHTML = `<div class="card flush">${ws.length ? `<div class="table-wrap"><table class="t"><thead><tr><th>Name</th><th>Employee ID</th><th>Site</th><th class="n">Tagged in</th><th>Status</th>${mgr ? '<th></th>' : ''}</tr></thead><tbody>
    ${ws.map(w => `<tr style="${w.active ? '' : 'opacity:.55'}"><td><div class="person-cell"><span class="avatar" style="width:28px;height:28px;font-size:11px">${esc(w.name.slice(0, 2).toUpperCase())}</span><span class="nm">${esc(w.name)}</span></div></td>
      <td>${esc(w.employee_id || '—')}</td><td class="muted">${esc(w.site_name || 'All sites')}</td><td class="n">${w.tagged} clip${w.tagged === 1 ? '' : 's'}</td>
      <td>${w.active ? '<span class="badge ok">Active</span>' : '<span class="badge flat">Inactive</span>'}</td>
      ${mgr ? `<td class="n"><button class="btn xs ghost" data-edit="${w.id}">${icon('pencil')}</button><button class="btn xs ghost" data-tog="${w.id}">${w.active ? 'Deactivate' : 'Activate'}</button></td>` : ''}</tr>`).join('')}</tbody></table></div>`
    : `<div style="padding:20px">${empty('users', mgr ? 'No workers yet. Add them one by one or import a CSV with columns <code>name, employee_id, site</code>.' : 'No workers yet.')}</div>`}</div>`;
  $$('[data-edit]', box).forEach(b => b.onclick = () => editWorker(ws.find(w => w.id === +b.dataset.edit), () => renderWorkers(box, actions)));
  $$('[data-tog]', box).forEach(b => b.onclick = async () => { const w = ws.find(x => x.id === +b.dataset.tog); await api(`/api/workers/${w.id}`, { method: 'PATCH', body: { active: w.active ? 0 : 1 } }).catch(fail); renderWorkers(box, actions); });
}

function editWorker(w, done) {
  formModal(w ? 'Edit worker' : 'Add worker',
    field('Full name', `<input type="text" name="name" value="${esc(w?.name || '')}" required>`) +
    field('Employee ID', `<input type="text" name="employee_id" value="${esc(w?.employee_id || '')}" placeholder="As in greytHR / Keka / Zoho">`, 'Used in payroll exports.') +
    field('Site', `<select name="site_id"><option value="">All sites</option>${S.me.sites.map(s => opt(s.id, s.name, w?.site_id)).join('')}</select>`),
    async fd => {
      const b = Object.fromEntries(fd); b.site_id = b.site_id ? +b.site_id : null;
      await api(w ? `/api/workers/${w.id}` : '/api/workers', { method: w ? 'PATCH' : 'POST', body: b }); done();
    });
}

/* ---------- cameras ---------- */
export async function camerasPage() {
  const el = mount('cameras', `<b>${t('nav.cameras')}</b>`, `<div class="page-head"><div><h1>${t('nav.cameras')}</h1><p>Each camera has a zone template, shifts, and an edge agent that slices RTSP recordings by shift and uploads them.</p></div><div class="actions" id="cact"></div></div><div id="cbox"></div>`);
  await renderCameras($('#cbox', el), $('#cact', el));
}

const HEALTH = { online: 'Online', offline: 'Offline', rtsp: 'RTSP (no agent)', not_connected: 'Not connected' };

export async function renderCameras(box, actions = box) {
  const [cams, vids] = await Promise.all([api('/api/cameras'), api('/api/videos')]);
  const mgr = isManager();
  if (mgr) {
    const bar = document.createElement('div'); bar.className = 'row';
    bar.innerHTML = `<button class="btn primary" id="cadd">${icon('plus')}Add camera</button>`;
    actions === box ? box.before(bar) : actions.replaceChildren(bar);
    $('#cadd', bar).onclick = () => editCamera(null, () => renderCameras(box, actions));
  }
  box.innerHTML = cams.length ? `<div class="grid g-3">${cams.map(c => {
    const last = vids.find(v => v.camera_id === c.id);
    return `<div class="card"><div class="card-head"><h3>${esc(c.name)}</h3><span class="spacer"></span><span class="health ${c.health}">${HEALTH[c.health]}</span></div>
      <div class="small muted" style="display:grid;gap:4px">
        <div>${icon('building', 'ic12')} ${esc(c.site_name || '—')}${c.location ? ` · ${esc(c.location)}` : ''}${c.brand ? ` · ${esc(c.brand)}` : ''}</div>
        <div>${icon('clock', 'ic12')} ${c.shifts.map(s => `${esc(s.name)} ${esc(s.start)}–${esc(s.end)}`).join(', ')}${c.auto_slice ? '' : ' · auto-slice off'}</div>
        <div>${icon('map', 'ic12')} ${c.zones.length} zone${c.zones.length === 1 ? '' : 's'} in template · ${c.clips} clip${c.clips === 1 ? '' : 's'}</div>
        <div>${icon('video', 'ic12')} Last clip received: ${c.last_clip_at ? ago(c.last_clip_at) : 'never'}${c.agent_last_seen ? ` · agent seen ${ago(c.agent_last_seen)}` : ''}</div>
        ${c.rtsp_url ? `<div style="word-break:break-all"><code>${esc(c.rtsp_url)}</code></div>` : ''}
      </div>
      ${mgr ? `<div class="row" style="margin-top:14px;gap:6px">
        <button class="btn sm" data-zones="${c.id}" data-last="${last?.run_id || ''}" data-lastv="${last?.id || ''}">${icon('map')}Zones</button>
        <button class="btn sm" data-pair="${c.id}">${icon('key')}${c.paired ? 'Agent' : 'Pair agent'}</button>
        ${c.rtsp_url ? `<button class="btn sm" data-snap="${c.id}">${icon('camera')}</button><button class="btn sm" data-rec="${c.id}" title="Record a test clip">${icon('video')}</button>` : ''}
        <span class="spacer"></span><button class="btn sm ghost" data-edit="${c.id}">${icon('pencil')}</button><button class="btn sm ghost danger" data-del="${c.id}">${icon('trash')}</button></div>` : ''}</div>`;
  }).join('')}</div>` : empty('cctv', mgr ? 'No cameras yet. Add one, pair the edge agent, and shift recordings arrive here automatically.' : 'No cameras yet.');
  const re = () => renderCameras(box, actions);
  const byId = id => cams.find(c => c.id === +id);
  $$('[data-edit]', box).forEach(b => b.onclick = () => editCamera(byId(b.dataset.edit), re));
  $$('[data-del]', box).forEach(b => b.onclick = async () => {
    if (!await confirmBox('Remove camera?', 'Its footage and reports stay. The edge agent token stops working.', { label: t('delete'), danger: true })) return;
    await api(`/api/cameras/${b.dataset.del}`, { method: 'DELETE' }).catch(fail); re();
  });
  $$('[data-pair]', box).forEach(b => b.onclick = async () => {
    const c = byId(b.dataset.pair);
    if (c.paired && !await confirmBox('Issue a new agent token?', 'The current agent stops uploading until you update its token.', { label: 'Rotate token' })) return;
    const r = await api(`/api/cameras/${c.id}/pair`, { method: 'POST' }).catch(fail);
    if (!r) return;
    modal(`<h3>Edge agent for ${esc(c.name)}</h3><p class="muted small">Run this on a small PC or NVR-side box on the camera network (needs Python 3 and ffmpeg). It records each shift from RTSP, marks gaps when the feed drops, and uploads slices with resumable uploads. The token is shown once.</p>
      <pre id="cmd">${esc(r.command)}</pre><div class="mfoot"><button class="btn" id="cp">${icon('copy')}Copy command</button><button class="btn primary" data-close>Done</button></div>`, { size: 'mid' });
    $('#cp').onclick = () => copyText(r.command);
    re();
  });
  $$('[data-snap]', box).forEach(b => b.onclick = () => {
    const m = modal(`<h3>Live snapshot</h3><p class="muted small" id="sn">Grabbing a frame from the stream…</p><img src="/api/cameras/${b.dataset.snap}/snapshot.jpg?${Date.now()}" style="width:100%;border-radius:10px"><div class="mfoot"><button class="btn" data-close>${t('close')}</button></div>`);
    const img = $('img', m); img.onload = () => $('#sn', m).remove(); img.onerror = () => { $('#sn', m).textContent = 'Could not read a frame — check the URL, credentials and network.'; img.remove(); };
  });
  $$('[data-rec]', box).forEach(b => b.onclick = () => formModal('Record a test clip', field('Minutes', '<input type="number" name="minutes" value="2" min="0.25" max="60" step="0.25" required>', 'Captured by the server and analysed automatically. Use the edge agent for full shifts.'),
    async fd => { await api(`/api/cameras/${b.dataset.rec}/record`, { method: 'POST', body: { minutes: +fd.get('minutes') } }); toast('Recording started — the clip appears in Videos when done'); }, { label: 'Start' }));
  $$('[data-zones]', box).forEach(b => b.onclick = () => zoneTemplate(byId(b.dataset.zones), b.dataset.last, b.dataset.lastv, re));
}

function editCamera(c, done) {
  const shifts = c?.shifts || [{ name: 'General', start: '09:00', end: '18:00' }];
  const shiftRow = (s, i) => `<div class="row shift" style="gap:6px;margin-bottom:6px"><input type="text" value="${esc(s.name)}" placeholder="Shift" data-k="name" style="flex:1"><input type="time" value="${esc(s.start)}" data-k="start" style="width:120px"><input type="time" value="${esc(s.end)}" data-k="end" style="width:120px"><button type="button" class="btn xs ghost" data-rm>${icon('x')}</button></div>`;
  const m = formModal(c ? `Edit ${c.name}` : 'Add camera', `
    <div class="grid g-2" style="gap:12px">${field('Name', `<input type="text" name="name" value="${esc(c?.name || '')}" required placeholder="Bay 1 — overhead">`)}${field('Location', `<input type="text" name="location" value="${esc(c?.location || '')}" placeholder="Fabrication hall">`)}</div>
    <div class="grid g-2" style="gap:12px">${field('Site', `<select name="site_id">${S.me.sites.map(s => opt(s.id, s.name, c?.site_id)).join('')}</select>`)}${field('Brand / NVR', `<input type="text" name="brand" value="${esc(c?.brand || '')}" placeholder="Hikvision, CP Plus, Dahua…">`)}</div>
    ${field('RTSP URL', `<input type="text" name="rtsp_url" value="${esc(c?.rtsp_url || '')}" placeholder="rtsp://user:pass@192.168.1.64:554/Streaming/Channels/101">`, 'Stored on the server and sent only to the paired edge agent. Shown masked.')}
    <div class="field"><label>Shifts</label><div id="shifts">${shifts.map(shiftRow).join('')}</div><button type="button" class="btn xs" id="addshift" style="align-self:flex-start">${icon('plus')}Add shift</button></div>
    <label class="check"><input type="checkbox" name="auto_slice" ${c?.auto_slice === 0 ? '' : 'checked'}> Auto-slice recordings by shift and upload them</label>`,
    async fd => {
      const b = Object.fromEntries(fd);
      b.site_id = +b.site_id; b.auto_slice = fd.get('auto_slice') ? 1 : 0;
      b.shifts = $$('.shift', m).map(r => Object.fromEntries($$('[data-k]', r).map(i => [i.dataset.k, i.value]))).filter(s => s.name);
      await api(c ? `/api/cameras/${c.id}` : '/api/cameras', { method: c ? 'PATCH' : 'POST', body: b }); done();
    }, { size: 'mid', label: c ? t('save') : 'Add camera' });
  const wire = () => $$('[data-rm]', m).forEach(x => x.onclick = () => x.closest('.shift').remove());
  $('#addshift', m).onclick = () => { $('#shifts', m).insertAdjacentHTML('beforeend', shiftRow({ name: '', start: '18:00', end: '02:00' })); wire(); };
  wire();
}

function zoneTemplate(cam, runId, vidId, done) {
  const src = runId ? `/api/runs/${runId}/ref.jpg` : vidId ? `/api/videos/${vidId}/frame.jpg` : cam.rtsp_url ? `/api/cameras/${cam.id}/snapshot.jpg?${Date.now()}` : null;
  if (!src) return toast('No frame to draw on yet — add an RTSP URL or wait for the first clip from this camera.', true);
  const m = modal(`<h3>Zone template — ${esc(cam.name)}</h3><p class="muted small" style="margin:0 0 12px">New slices from this camera start with these zones. Existing footage keeps its own zones.</p>
    <div class="stage"><img class="bg" alt=""></div><div class="toolbar" id="zt"></div><div class="zone-list" id="zl"></div>
    <div class="mfoot"><button class="btn" data-close>${t('cancel')}</button><button class="btn primary" id="zs">Save template</button></div>`);
  const img = $('img', m);
  img.onerror = () => toast('Could not load a frame for this camera.', true);
  img.src = src;
  const ov = new Overlay($('.stage', m), img, { zones: structuredClone(cam.zones) });
  zoneTools(ov, $('#zt', m), $('#zl', m));
  ov.setEditing(true);
  m.addEventListener('closed', () => ov.destroy());
  $('#zs', m).onclick = async () => { try { await api(`/api/cameras/${cam.id}`, { method: 'PATCH', body: { zones: ov.zones } }); m.close(); toast('Zone template saved'); done(); } catch (e) { fail(e); } };
}
