import { $, $$, S, t, esc, icon, api, toast, fail, modal, formModal, confirmBox, isManager, canReview, hm, hms, clock, fmtTs, fmtDay, ago,
  STATES, STATE_COLOR, stateLabel, stateChip, statusBadge, pctBar, field, opt, empty, onLeave, todayIST, download, zoneLabel } from '../core.js';
import { mount } from '../main.js';
import { Overlay, zoneTools } from '../overlay.js';

const FILTERS = [['', 'All'], ['analysing', 'Analysing'], ['annotate', 'Annotate'], ['review', 'Review pending'], ['report_ready', 'Report ready'], ['sent', 'Sent'], ['failed', 'Failed']];

/* ---------- library ---------- */
export async function videosPage() {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  const filter = params.get('status') || '';
  const [vids, cams] = await Promise.all([api('/api/videos'), api('/api/cameras')]);
  const shown = vids.filter(v => !filter || v.status === filter || (filter === 'analysing' && v.status === 'queued'));
  const count = k => vids.filter(v => !k || v.status === k || (k === 'analysing' && v.status === 'queued')).length;
  const el = mount('videos', `<b>${t('nav.videos')}</b>`, `
    <div class="page-head"><div><h1>${t('nav.videos')}</h1><p>Uploads and camera slices move through: Uploaded → Analysing → Annotate → Review → Report ready → Sent.</p></div>
      <div class="actions">${isManager() ? `<button class="btn primary" id="upload">${icon('upload')}${t('upload_footage')}</button>` : ''}</div></div>
    <div class="tabs">${FILTERS.map(([k, l]) => `<a href="#/videos${k ? `?status=${k}` : ''}" class="${filter === k ? 'active' : ''}">${l}<span class="count">${count(k)}</span></a>`).join('')}</div>
    ${shown.length ? `<div class="vgrid">${shown.map(videoCard).join('')}</div>`
      : empty('video', vids.length ? 'Nothing in this state.' : isManager() ? 'No footage yet. Upload a recording or connect a camera.' : 'No footage yet. A manager needs to upload footage.')}`);
  $('#upload', el)?.addEventListener('click', () => uploadModal(cams));
  if (params.get('upload') && isManager()) uploadModal(cams);
  if (vids.some(v => ['queued', 'analysing'].includes(v.status))) { const tm = setTimeout(() => location.hash.startsWith('#/videos') && videosPage(), 3000); onLeave(() => clearTimeout(tm)); }
}

function videoCard(v) {
  const prog = ['analysing', 'queued'].includes(v.status) ? `<div class="progress" style="margin-top:10px"><div style="width:${Math.round((v.job?.progress || 0) * 100)}%"></div></div>` : '';
  const thumb = v.run_id ? `/api/runs/${v.run_id}/ref.jpg` : `/api/videos/${v.id}/frame.jpg?t=${Math.min(1, (v.duration || 0) / 2)}`;
  return `<a class="vcard" href="#/videos/${v.id}">
    <div class="thumb" style="background-image:url('${v.footage_deleted && !v.run_id ? '' : thumb}')">${statusBadge(v)}<span class="dur">${clock(v.duration)}</span></div>
    <div class="body"><div class="title">${esc(v.name)}${v.is_demo ? ' <span class="badge info">demo</span>' : ''}${v.partial ? ' <span class="badge warn" title="Partial footage">partial</span>' : ''}</div>
      <div class="meta">${icon(v.source === 'camera' ? 'cctv' : 'upload', 'ic12')} ${esc(v.camera_name || 'Upload')}${v.shift ? ` · ${esc(v.shift)}` : ''} · ${fmtDay(v.recorded_on)}</div>
      ${v.run_id ? `<div class="sum"><span><b>${v.people}</b> people</span>${v.pending ? `<span style="color:var(--accent)"><b style="color:inherit">${v.pending}</b> to review</span>` : ''}</div>` : ''}
      ${v.status === 'failed' ? `<div class="small" style="color:#ff8f88;margin-top:8px">${esc(v.job?.error || 'Analysis failed')}</div>` : ''}${prog}</div></a>`;
}

function uploadModal(cams) {
  const m = modal(`<h3>${t('upload_footage')}</h3><p class="muted small" style="margin:0 0 16px">Resumable upload — large CCTV exports continue where they left off if the connection drops. MP4, MOV, MKV, AVI or TS.</p><form>
    ${field('Video file', '<input type="file" name="file" accept="video/*,.mkv,.ts" required>')}
    ${field('Name', '<input type="text" name="name" placeholder="Defaults to the file name">')}
    <div class="grid g-2" style="gap:12px">${field('Recorded on', `<input type="date" name="recorded_on" value="${todayIST()}">`)}
      ${field('Shift', '<input type="text" name="shift" placeholder="e.g. General / A / Night">')}</div>
    <div class="grid g-2" style="gap:12px">${field('Camera', `<select name="camera_id"><option value="">— none —</option>${cams.map(c => opt(c.id, c.name)).join('')}</select>`, 'Copies the camera’s zone template onto the video.')}
      ${field('Site', `<select name="site_id"><option value="">— default —</option>${S.me.sites.map(s => opt(s.id, s.name)).join('')}</select>`)}</div>
    <label class="check"><input type="checkbox" name="partial"> Footage is partial (camera dropped or recording has gaps)</label>
    <div id="up-state" hidden><div class="row small muted" style="margin-bottom:6px"><span id="up-txt">Uploading…</span><span class="spacer"></span><span id="up-pct">0%</span></div><div class="progress"><div style="width:0"></div></div></div>
    <div class="error" hidden></div>
    <div class="mfoot"><button type="button" class="btn" data-close>${t('cancel')}</button><button type="button" class="btn" id="pause" hidden>Pause</button><button class="btn primary">${icon('upload')}${t('upload')}</button></div></form>`, { size: 'mid' });
  let up = null;
  m.addEventListener('closed', () => up?.abort());
  $('form', m).onsubmit = e => {
    e.preventDefault();
    const fd = new FormData(e.target), file = fd.get('file');
    if (!window.tus) return fail(new Error('Upload library failed to load — check your internet connection.'));
    const meta = { filename: file.name, name: fd.get('name') || file.name.replace(/\.[^.]+$/, ''), recorded_on: fd.get('recorded_on'), shift: fd.get('shift'),
      camera_id: fd.get('camera_id'), site_id: fd.get('site_id'), partial: fd.get('partial') ? '1' : '' };
    $('#up-state', m).hidden = false; $('button.primary', m).disabled = true; $('#pause', m).hidden = false;
    const t0 = Date.now();
    up = new tus.Upload(file, {
      endpoint: '/api/tus/', chunkSize: 16 * 1024 * 1024, retryDelays: [0, 1000, 3000, 5000, 10000], metadata: meta, removeFingerprintOnSuccess: true,
      onProgress: (sent, total) => {
        const pct = 100 * sent / total, mbps = sent / 1e6 / Math.max(1, (Date.now() - t0) / 1000);
        $('.progress div', m).style.width = pct + '%'; $('#up-pct', m).textContent = pct.toFixed(1) + '%';
        $('#up-txt', m).textContent = `Uploading ${(sent / 1e6).toFixed(0)} / ${(total / 1e6).toFixed(0)} MB · ${mbps.toFixed(1)} MB/s`;
      },
      onError: err => { const el = $('.error', m); el.hidden = false; el.textContent = (err.originalResponse?.getBody?.() && safeDetail(err.originalResponse.getBody())) || err.message; $('button.primary', m).disabled = false; },
      onSuccess: async () => {
        const st = await api(`/api/uploads/${up.url.split('/').pop()}`);
        m.close(); toast('Uploaded — analysis queued'); location.hash = `#/videos/${st.video_id}`;
      },
    });
    up.findPreviousUploads().then(prev => { if (prev.length) up.resumeFromPreviousUpload(prev[0]); up.start(); });
  };
  let paused = false;
  $('#pause', m).onclick = () => { paused = !paused; paused ? up.abort() : up.start(); $('#pause', m).textContent = paused ? 'Resume' : 'Pause'; $('#up-txt', m).textContent = paused ? 'Paused' : 'Resuming…'; };
}
const safeDetail = b => { try { return JSON.parse(b).detail; } catch { return ''; } };

/* ---------- processing queue ---------- */
export async function jobsPage() {
  const jobs = await api('/api/jobs');
  const cls = { queued: 'warn', analysing: 'warn', complete: 'ok', failed: 'err' };
  const el = mount('jobs', `<b>${t('nav.jobs')}</b>`, `
    <div class="page-head"><div><h1>${t('nav.jobs')}</h1><p>Detection + tracking runs on GPU workers. Jobs retry once automatically before they fail.</p></div></div>
    <div class="card flush">${jobs.length ? `<div class="table-wrap"><table class="t"><thead><tr><th>Footage</th><th>Status</th><th style="width:22%">Progress</th><th>Worker</th><th>Queued</th><th class="n">Duration</th><th></th></tr></thead><tbody>
      ${jobs.map(j => `<tr><td><a href="#/videos/${j.video_id}">${esc(j.video_name)}</a>${j.error ? `<div class="small" style="color:#ff8f88">${esc(j.error)}</div>` : ''}</td>
        <td><span class="badge ${cls[j.status]}"><span class="d"></span>${esc(j.status === 'analysing' ? 'Analysing' : j.status[0].toUpperCase() + j.status.slice(1))}</span></td>
        <td><div class="progress"><div style="width:${Math.round(j.progress * 100)}%"></div></div></td>
        <td class="small muted">${esc(j.worker || '—')}${j.attempts > 1 ? ` · try ${j.attempts}` : ''}</td><td class="small muted">${ago(j.created_at)}</td>
        <td class="n">${j.finished_at && j.started_at ? hm(j.finished_at - j.started_at) : '—'}</td>
        <td class="n">${j.status === 'failed' && isManager() ? `<button class="btn xs" data-retry="${j.id}">${icon('refresh')}Retry</button>` : ''}</td></tr>`).join('')}</tbody></table></div>`
      : `<div style="padding:20px">${empty('gpu', 'No analysis jobs yet.')}</div>`}</div>
    <div class="card" style="margin-top:20px"><h3>Scale out with GPU workers</h3><p class="muted small" style="margin-top:0">Any machine with an NVIDIA GPU can pull jobs from this queue. Set <code>WW_WORKER_TOKEN</code> on the server, then on the GPU box:</p>
      <pre>pip install -r requirements.txt
python -m workwatch worker --server ${esc(location.origin)} --token $WW_WORKER_TOKEN</pre></div>`);
  $$('[data-retry]', el).forEach(b => b.onclick = async () => { await api(`/api/jobs/${b.dataset.retry}/retry`, { method: 'POST' }).catch(fail); jobsPage(); });
  if (jobs.some(j => ['queued', 'analysing'].includes(j.status))) { const tm = setTimeout(() => location.hash.startsWith('#/jobs') && jobsPage(), 3000); onLeave(() => clearTimeout(tm)); }
}

/* ---------- video detail ---------- */
const STEPS = ['uploaded', 'analysing', 'annotate', 'review', 'report_ready', 'sent'];
let tab = 'annotate';

export async function videoPage(id) {
  const data = await api(`/api/videos/${id}/results`);
  const v = data.video, run = data.run, people = data.people;
  const busy = ['queued', 'analysing'].includes(v.status);
  if (!run && tab !== 'details') tab = 'details';
  if (run && !v.annotated && tab === 'timeline' && !sessionStorage.getItem('ww_tl_ok')) tab = 'annotate';
  const stepIdx = { uploaded: 0, slice: 0, queued: 1, analysing: 1, failed: 1, annotate: 2, review: 3, report_ready: 4, sent: 5 }[v.status];
  const el = mount('videos', `<a href="#/videos" style="text-decoration:none">${t('nav.videos')}</a>${icon('chevron', 'ic12')}<b>${esc(v.name)}</b>`, `
    <div class="page-head"><div><h1>${esc(v.name)} ${v.is_demo ? '<span class="badge info">demo</span>' : ''}</h1>
      <p>${esc(v.camera_name || 'Uploaded file')}${v.site_name ? ` · ${esc(v.site_name)}` : ''}${v.shift ? ` · Shift ${esc(v.shift)}` : ''} · ${fmtDay(v.recorded_on)} · ${clock(v.duration)} · ${v.width}×${v.height}</p></div>
      <div class="actions">${statusBadge(v)}${v.pending && v.annotated && canReview() ? `<a class="btn sm" href="#/review?video=${v.id}">${icon('review')}Review ${v.pending}</a>` : ''}
        ${v.status === 'report_ready' || v.status === 'sent' ? `<a class="btn sm primary" href="#/reports?video=${v.id}">${icon('file')}Report</a>` : ''}</div></div>
    <div class="stepper">${STEPS.map((s, i) => `<div class="step ${i < stepIdx ? 'done' : i === stepIdx ? 'cur' : ''}"><div class="bar-s"></div><span>${esc(t(`status.${s === 'uploaded' && v.source === 'camera' ? 'slice' : s}`))}</span></div>`).join('')}</div>
    ${v.partial ? `<div class="banner">${icon('alert')}<div><b>Partial footage.</b> ${esc(v.gap_note || 'The recording has gaps.')} Reports will carry this note.</div></div>` : ''}
    ${busy ? `<div class="card" style="margin-bottom:20px"><div class="row"><b>${v.status === 'queued' ? 'Waiting for a GPU worker…' : 'Detecting and tracking people…'}</b><span class="spacer"></span><span class="muted">${Math.round((v.job?.progress || 0) * 100)}%</span></div>
      <div class="progress" style="margin-top:10px"><div style="width:${Math.round((v.job?.progress || 0) * 100)}%"></div></div><p class="faint small" style="margin:8px 0 0">YOLOv8 person + phone detection, ByteTrack, pose check on phone frames. You can leave this page.</p></div>` : ''}
    ${v.status === 'failed' ? `<div class="banner err">${icon('alert')}<div><b>Analysis failed.</b> ${esc(v.job?.error || '')}</div>${isManager() ? '<button class="btn sm" id="rerun2">Retry</button>' : ''}</div>` : ''}
    <div class="tabs">${run ? `<button data-tab="annotate" class="${tab === 'annotate' ? 'active' : ''}">${icon('users')}People & zones${!v.annotated ? ' <span class="count" style="background:var(--accent);color:var(--accent-ink)">to do</span>' : ''}</button>
      <button data-tab="timeline" class="${tab === 'timeline' ? 'active' : ''}">${icon('play')}Timeline</button>` : ''}
      <button data-tab="details" class="${tab === 'details' ? 'active' : ''}">${icon('info')}Details & files</button></div>
    <div id="pane"></div>`);
  $$('[data-tab]', el).forEach(b => b.onclick = () => { tab = b.dataset.tab; if (tab === 'timeline') sessionStorage.setItem('ww_tl_ok', 1); videoPage(id); });
  $('#rerun2', el)?.addEventListener('click', () => reanalyse(v));
  const pane = $('#pane', el);
  if (tab === 'annotate' && run) annotatePane(pane, v, run, people, data.workers);
  else if (tab === 'timeline' && run) timelinePane(pane, v, run, people);
  else detailsPane(pane, v, run);
  if (busy) { const tm = setTimeout(() => location.hash === `#/videos/${id}` && videoPage(id), 2500); onLeave(() => clearTimeout(tm)); }
}

const rerender = v => videoPage(v.id);
async function reanalyse(v) {
  if (v.run_id && !await confirmBox('Re-run analysis?', 'Detection and tracking run again on a GPU worker. Names and removals carry over by track; review decisions on unchanged segments are kept.', { label: 'Re-analyse' })) return;
  try { await api(`/api/videos/${v.id}/analyze`, { method: 'POST' }); toast('Queued for analysis'); rerender(v); } catch (e) { fail(e); }
}

/* --- annotate: reference frame, keep/remove, names, merge, zones --- */
function annotatePane(pane, v, run, people, workers) {
  const mgr = isManager();
  const byTrack = {};
  people.forEach(p => { byTrack[p.track_id] = p; (p.merged || []).forEach(m => { byTrack[m.track_id] = p; }); });
  const roots = people;
  let selected = null, mode = 'people', dirty = false;
  pane.innerHTML = `
    ${v.annotated ? `<div class="banner ok">${icon('check')}<div><b>Annotation complete.</b> Changes here re-classify instantly; the review queue updates to match.</div>${mgr ? '<button class="btn sm" id="reopen">Reopen</button>' : ''}</div>`
      : `<div class="banner info">${icon('info')}<div><b>Step 3 — annotate.</b> Name each worker from your list, remove visitors or reflections, merge tracks that are the same person, and confirm the zones. Then finish to send flagged items to review.</div></div>`}
    <div class="grid g-side">
      <div>
        <div class="row" style="margin-bottom:10px"><div class="seg"><button data-mode="people" class="active">${icon('users', 'ic12')} Detections</button>${mgr ? `<button data-mode="zones">${icon('map', 'ic12')} Zones</button>` : ''}</div>
          <span class="spacer"></span><span class="faint small" id="mode-hint">Reference frame at ${clock(run.ref?.t || 0)} · click a box to select that person</span></div>
        <div class="stage" id="stage"><img class="bg" src="/api/runs/${run.id}/ref.jpg" alt="Reference frame"></div>
        <div id="zone-ui" hidden><div class="toolbar" id="ztools"></div><div class="zone-list" id="zlist"></div>
          <div class="row" style="margin-top:14px">${v.camera_id ? `<label class="check" style="margin:0"><input type="checkbox" id="tpl"> Save as zone template for ${esc(v.camera_name)}</label>` : ''}<span class="spacer"></span>
            <button class="btn" id="zreset">Reset</button><button class="btn primary" id="zsave" disabled>Save zones</button></div></div>
        <div class="legend" style="margin-top:12px"><span><span class="dot" style="background:#eeb23e"></span>Kept detection</span><span><span class="dot" style="background:#5a6577"></span>Removed</span><span><span class="dot" style="background:#fff"></span>Selected</span></div>
      </div>
      <div class="card"><div class="card-head"><h3>People in this clip</h3><span class="sub">${roots.filter(p => !p.removed).length} kept · ${roots.filter(p => p.removed).length} removed</span></div>
        <div class="people" id="plist"></div>
        ${mgr ? `<div style="margin-top:16px;border-top:1px solid var(--border);padding-top:14px">
          ${!v.annotated ? `<button class="btn primary block" id="finish">${icon('check')}Finish annotation</button><p class="faint small" style="margin:8px 0 0">${v.pending} segment(s) will go to the review queue.</p>` : ''}</div>` : ''}
      </div>
    </div>`;
  const img = $('#stage img', pane);
  const ov = new Overlay($('#stage', pane), img, { zones: structuredClone(v.zones), onPick: b => select(b.person.id) });
  onLeave(() => ov.destroy());
  const boxes = () => (run.ref?.boxes || []).map(b => ({ ...b, person: byTrack[b.track_id] })).filter(b => b.person)
    .map(b => ({ box: b.box, person: b.person, label: b.person.worker_name || b.person.label, removed: !!b.person.removed, selected: b.person.id === selected }));
  ov.setStatic(boxes());
  const list = $('#plist', pane);
  const workerOpts = sel => `<option value="">— name from worker list —</option>${workers.map(w => opt(w.id, w.name + (w.employee_id ? ` · ${w.employee_id}` : ''), sel)).join('')}<option value="__new">+ Add new worker…</option>`;
  const renderList = () => {
    list.innerHTML = roots.map(p => `<div class="person ${p.removed ? 'removed' : ''} ${p.id === selected ? 'hl' : ''}" data-pid="${p.id}">
      ${p.thumb ? `<img src="/api/runs/${run.id}/thumbs/${esc(p.thumb)}" alt="">` : '<div class="ph"></div>'}
      <div style="min-width:0"><div class="nm">${esc(p.worker_name || p.label)}</div>
        <div class="nums"><span>${hm(p.present_s)} seen</span>${p.merged?.length ? `<span>+${p.merged.length} merged</span>` : ''}${p.pending ? `<span style="color:var(--accent)">${p.pending} flagged</span>` : ''}</div>
        ${mgr ? `<div class="row" style="gap:6px;margin-top:6px"><select data-worker="${p.id}" aria-label="Worker">${workerOpts(p.worker_id)}</select>
          <select data-merge="${p.id}" aria-label="Merge"><option value="">Merge into…</option>${roots.filter(o => o.id !== p.id).map(o => opt(o.id, o.worker_name || o.label)).join('')}</select></div>
          ${p.merged?.length ? `<div class="small faint" style="margin-top:4px">Merged tracks: ${p.merged.map(mm => `#${mm.track_id} <a href="#" data-unmerge="${mm.id}" style="color:var(--accent)">undo</a>`).join(', ')}</div>` : ''}` : ''}
      </div>
      ${mgr ? `<label class="switch" title="${p.removed ? 'Removed — not counted' : 'Kept — counted in reports'}"><input type="checkbox" data-keep="${p.id}" ${p.removed ? '' : 'checked'}><span></span></label>` : ''}</div>`).join('');
    $$('[data-pid]', list).forEach(row => row.addEventListener('click', e => { if (!e.target.closest('select,input,a,label')) select(+row.dataset.pid); }));
    $$('[data-keep]', list).forEach(cb => cb.onchange = () => act(`/api/persons/${cb.dataset.keep}`, 'PATCH', { removed: !cb.checked }));
    $$('[data-worker]', list).forEach(s => s.onchange = async () => {
      if (s.value === '__new') {
        return formModal('Add worker', field('Full name', '<input type="text" name="name" required>') + field('Employee ID', '<input type="text" name="employee_id" placeholder="Matches your payroll system">'),
          async fd => { const w = await api('/api/workers', { method: 'POST', body: Object.fromEntries(fd) }); await act(`/api/persons/${s.dataset.worker}`, 'PATCH', { worker_id: w.id }); }, { label: 'Add & assign' });
      }
      act(`/api/persons/${s.dataset.worker}`, 'PATCH', { worker_id: s.value ? +s.value : null });
    });
    $$('[data-merge]', list).forEach(s => s.onchange = async () => {
      if (!s.value) return;
      const a = roots.find(p => p.id === +s.dataset.merge), b = roots.find(p => p.id === +s.value);
      if (await confirmBox('Merge tracks?', `Treat <b>${esc(a.worker_name || a.label)}</b> as the same person as <b>${esc(b.worker_name || b.label)}</b>. Their time is combined (overlaps counted once).`, { label: 'Merge' }))
        act(`/api/persons/${s.dataset.merge}/merge`, 'POST', { into: +s.value }); else s.value = '';
    });
    $$('[data-unmerge]', list).forEach(a => a.onclick = e => { e.preventDefault(); act(`/api/persons/${a.dataset.unmerge}/unmerge`, 'POST'); });
  };
  const select = pid => { selected = selected === pid ? null : pid; ov.setStatic(boxes()); renderList(); $(`[data-pid="${pid}"]`, list)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); };
  const act = async (url, method, body) => { try { await api(url, { method, body }); rerender(v); } catch (e) { fail(e); } };
  renderList();

  $$('[data-mode]', pane).forEach(b => b.onclick = () => {
    mode = b.dataset.mode; $$('[data-mode]', pane).forEach(x => x.classList.toggle('active', x === b));
    $('#zone-ui', pane).hidden = mode !== 'zones';
    ov.setEditing(mode === 'zones');
    ov.setStatic(mode === 'zones' ? [] : boxes());
    $('#mode-hint', pane).textContent = mode === 'zones' ? 'Feet (bottom-centre of each box) decide which zone a person is in.' : `Reference frame at ${clock(run.ref?.t || 0)} · click a box to select that person`;
  });
  if (mgr) {
    zoneTools(ov, $('#ztools', pane), $('#zlist', pane), { onChange: () => { dirty = true; $('#zsave', pane).disabled = false; } });
    $('#zreset', pane).onclick = () => { ov.zones = structuredClone(v.zones); ov.changed(); dirty = false; $('#zsave', pane).disabled = true; };
    $('#zsave', pane).onclick = async () => {
      try { await api(`/api/videos/${v.id}/zones`, { method: 'PUT', body: { zones: ov.zones, save_template: !!$('#tpl', pane)?.checked } }); toast('Zones saved — time re-classified'); rerender(v); }
      catch (e) { fail(e); }
    };
    if (!v.zones.length) $('[data-mode="zones"]', pane).click();
  }
  $('#finish', pane)?.addEventListener('click', async () => {
    try { await api(`/api/videos/${v.id}/annotation/finish`, { method: 'POST' }); toast('Annotation finished'); tab = 'timeline'; sessionStorage.setItem('ww_tl_ok', 1); await (await import('../main.js')).refreshMe(); rerender(v); }
    catch (e) { fail(e); }
  });
  $('#reopen', pane)?.addEventListener('click', async () => { await api(`/api/videos/${v.id}/annotation/reopen`, { method: 'POST' }).catch(fail); rerender(v); });
}

/* --- timeline: playback with state boxes, 5-state rows, zone breakdown --- */
function timelinePane(pane, v, run, people) {
  const kept = people.filter(p => !p.removed);
  const dur = v.duration || 1;
  const ticks = Array.from({ length: 6 }, (_, i) => clock(dur * i / 5));
  pane.innerHTML = `
    ${v.footage_deleted ? `<div class="banner">${icon('info')}<div>Footage was deleted by the retention policy. Analysis and reports are kept.</div></div>` : ''}
    <div class="grid g-side">
      <div><div class="stage" id="stage">${v.footage_deleted ? `<img class="bg" src="/api/runs/${run.id}/ref.jpg">` : `<video src="/api/videos/${v.id}/stream" controls playsinline preload="metadata" muted></video>`}</div>
        <div class="toolbar"><label class="check" style="margin:0"><input type="checkbox" id="boxes" checked> Boxes</label><label class="check" style="margin:0"><input type="checkbox" id="zones" checked> Zones</label>
          ${S.me.face_blur ? '<span class="badge info">' + icon('eyeoff', 'ic12') + ' Face blur on</span>' : ''}<span class="spacer"></span>
          <div class="legend">${STATES.map(s => `<span><span class="dot" style="background:${STATE_COLOR[s]}"></span>${esc(stateLabel(s))}</span>`).join('')}<span><span class="dot" style="outline:2px solid #ff7a59"></span>Flagged</span></div></div></div>
      <div class="card scroll"><div class="card-head"><h3>Totals</h3><span class="sub">after review</span></div>
        <table class="t"><thead><tr><th>Person</th><th class="n">Working</th><th class="n">Eff.</th></tr></thead><tbody>
        ${kept.map(p => `<tr data-hl="${p.track_id}" style="cursor:pointer"><td><div class="nm">${esc(p.worker_name || p.label)}</div>${pctBar(p.totals, p.present_s)}</td><td class="n">${hm(p.working_s)}</td><td class="n">${p.efficiency}%</td></tr>`).join('')}</tbody></table></div>
    </div>
    <div class="card" style="margin-top:20px"><div class="card-head"><h2>Timeline</h2><span class="sub">click a segment to jump there</span></div>
      <div class="timeline">${kept.map(p => `<div class="tl-row"><div class="lbl" title="${esc(p.worker_name || p.label)}">${esc(p.worker_name || p.label)}</div>
        <div class="tl-track">${p.segments.map(s => `<div class="tl-seg ${s.flagged ? 'flagged' : ''} ${s.review_status === 'pending' ? 'pending' : ''}" data-t="${s.start}" style="left:${100 * s.start / dur}%;width:${100 * (s.end - s.start) / dur}%;background:${STATE_COLOR[s.effective_state]}"
          title="${esc(stateLabel(s.effective_state))} ${clock(s.start)}–${clock(s.end)}${s.zone ? ' · ' + esc(s.zone) : ''}${s.flag_reason ? ' · ' + esc(s.flag_reason) : ''}${s.review_status === 'reclassified' ? ' · reclassified from ' + esc(stateLabel(s.state)) : ''}"></div>`).join('')}<div class="tl-head" style="left:0"></div></div>
        <div class="tot">${hm(p.working_s)} · ${p.efficiency}%</div></div>`).join('') || '<p class="muted">Everyone in this clip was removed.</p>'}
      <div class="tl-axis"><span></span><div class="ticks">${ticks.map(x => `<span>${x}</span>`).join('')}</div><span></span></div></div></div>
    <div class="card flush" style="margin-top:20px"><div class="card-head" style="padding:18px 20px 0"><h2>Zone breakdown</h2></div><div class="table-wrap"><table class="t"><thead><tr><th>Person</th><th>Zone</th>${STATES.map(s => `<th class="n">${esc(stateLabel(s))}</th>`).join('')}</tr></thead><tbody>
      ${kept.flatMap(p => Object.entries(p.zone_totals).map(([z, d], i) => `<tr><td>${i ? '' : esc(p.worker_name || p.label)}</td><td>${esc(z)}</td>${STATES.map(s => `<td class="n">${d[s] ? hm(d[s]) : '<span class="faint">–</span>'}</td>`).join('')}</tr>`)).join('')}</tbody></table></div></div>`;
  const media = $('#stage video, #stage img', pane);
  const ov = new Overlay($('#stage', pane), media, { zones: v.zones, blur: S.me.face_blur });
  onLeave(() => ov.destroy());
  ov.labels = Object.fromEntries(people.map(p => [p.track_id, p.worker_name || p.label]));
  if (media.tagName === 'VIDEO') {
    api(`/api/runs/${run.id}/tracks`).then(tr => { ov.tracks = tr; ov.draw(); }).catch(() => { });
    const heads = $$('.tl-head', pane);
    const tick = () => heads.forEach(h => h.style.left = `${100 * media.currentTime / dur}%`);
    media.addEventListener('timeupdate', tick);
  }
  $('#boxes', pane).onchange = e => { ov.showBoxes = e.target.checked; ov.draw(); };
  $('#zones', pane).onchange = e => { ov.zones = e.target.checked ? v.zones : []; ov.draw(); };
  $$('.tl-seg', pane).forEach(s => s.onclick = () => { if (media.tagName === 'VIDEO') { media.currentTime = +s.dataset.t; media.play(); } });
  $$('[data-hl]', pane).forEach(r => r.onclick = () => { const tid = +r.dataset.hl; ov.highlight = ov.highlight === tid ? null : tid; ov.draw(); });
}

/* --- details: metadata, run stats, kit, import, download, delete --- */
function detailsPane(pane, v, run) {
  const mgr = isManager();
  const st = run?.stats || {}, pr = run?.params || {};
  const kv = (k, val) => `<div class="set-row"><div class="k"><b>${k}</b></div><div class="v" style="justify-content:flex-start">${val}</div></div>`;
  pane.innerHTML = `<div class="grid g-2">
    <div class="section"><div class="sh"><h2>Footage</h2></div><div class="sb">
      ${kv('Name', esc(v.name))}${kv('Recorded on', fmtDay(v.recorded_on))}${kv('Shift', esc(v.shift || '—'))}${kv('Camera', esc(v.camera_name || '—'))}
      ${kv('Source', v.source === 'camera' ? 'Camera slice (edge agent)' : 'Upload')}${kv('File', `${clock(v.duration)} · ${v.width}×${v.height} · ${(v.fps || 0).toFixed(1)} fps · ${((v.size || 0) / 1e6).toFixed(1)} MB`)}
      ${kv('Added', fmtTs(v.created_at))}${v.footage_deleted ? kv('Footage', '<span class="badge warn">deleted by retention policy</span>') : ''}
    </div>${mgr ? `<div class="sf"><button class="btn sm" id="edit">${icon('pencil')}Edit details</button></div>` : ''}</div>
    <div class="section"><div class="sh"><h2>Analysis</h2><p>${run ? `Run #${run.id} · ${fmtTs(run.created_at)}` : 'Not analysed yet'}</p></div><div class="sb">
      ${run ? kv('Model', `${esc(pr.model || '')} · pose ${esc(pr.pose_model || '—')}`) + kv('Device', esc(pr.device || '—')) + kv('Sampling', `${pr.sample_fps} fps · conf ${pr.det_conf}`) +
        kv('Speed', `${st.processing_s}s for ${clock(v.duration)} · ${st.realtime_x}× real time`) + kv('Tracks', `${st.tracks} · ${st.phone_frames || 0} phone frames · ${st.pose_frames || 0} pose checks`) +
        kv('Rules used', run.rules ? `idle ≥ ${run.rules.idle_threshold_s}s · phone ≥ ${run.rules.phone_threshold_s}s (gap ${run.rules.phone_gap_s}s)` : '—')
        : `<p class="muted" style="margin:0">${v.job ? esc(v.job.status) : 'No job yet'}.</p>`}
    </div>${mgr ? `<div class="sf"><button class="btn sm" id="rerun" ${['queued', 'analysing'].includes(v.status) || v.footage_deleted ? 'disabled' : ''}>${icon('refresh')}Re-analyse</button></div>` : ''}</div>
  </div>
  ${mgr ? `<div class="section"><div class="sh"><h2>Files</h2><p>Run the pipeline on your own hardware, or take the footage with you.</p></div><div class="sb"><div class="row">
    <a class="btn" href="/api/videos/${v.id}/kit">${icon('box')}Download pipeline kit</a>
    <label class="btn">${icon('upload')}Import results<input type="file" id="imp" accept=".zip,.json" hidden></label>
    ${v.footage_deleted ? '' : `<a class="btn" href="/api/videos/${v.id}/stream?download=1">${icon('download')}Download footage</a>`}
    <span class="spacer"></span><button class="btn danger" id="del">${icon('trash')}Delete video</button></div>
    <p class="faint small" style="margin:12px 0 0">The kit contains the YOLOv8 pipeline, this video’s zones and your analysis rules. Run <code>python analyze_video.py footage.mp4</code>, then import the <code>results.zip</code> here.</p></div></div>` : ''}`;
  $('#rerun', pane)?.addEventListener('click', () => reanalyse(v));
  $('#imp', pane)?.addEventListener('change', async e => {
    const fd = new FormData(); fd.append('file', e.target.files[0]);
    try { await api(`/api/videos/${v.id}/import-results`, { method: 'POST', body: fd }); toast('Results imported'); tab = 'annotate'; rerender(v); } catch (er) { fail(er); }
  });
  $('#del', pane)?.addEventListener('click', async () => {
    if (!await confirmBox('Delete this video?', 'The footage, its analysis and review decisions are removed. Reports already generated keep their numbers. This is recorded in the audit trail.', { label: t('delete'), danger: true })) return;
    await api(`/api/videos/${v.id}`, { method: 'DELETE' }).catch(fail); location.hash = '#/videos';
  });
  $('#edit', pane)?.addEventListener('click', () => api('/api/cameras').then(cams => formModal('Edit details',
    field('Name', `<input type="text" name="name" value="${esc(v.name)}" required>`) +
    `<div class="grid g-2" style="gap:12px">${field('Recorded on', `<input type="date" name="recorded_on" value="${esc(v.recorded_on || '')}">`)}${field('Shift', `<input type="text" name="shift" value="${esc(v.shift || '')}">`)}</div>` +
    `<div class="grid g-2" style="gap:12px">${field('Camera', `<select name="camera_id"><option value="">—</option>${cams.map(c => opt(c.id, c.name, v.camera_id)).join('')}</select>`)}${field('Site', `<select name="site_id"><option value="">—</option>${S.me.sites.map(s => opt(s.id, s.name, v.site_id)).join('')}</select>`)}</div>`,
    async fd => { const b = Object.fromEntries(fd); b.camera_id = b.camera_id ? +b.camera_id : null; b.site_id = b.site_id ? +b.site_id : null; await api(`/api/videos/${v.id}`, { method: 'PATCH', body: b }); rerender(v); }, { size: 'mid' })));
}
