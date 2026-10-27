/* WorkWatch dashboard — plain JS, no build step. Hash routes: #/, #/login, #/dashboard, #/videos, #/videos/:id, #/review, #/reports, #/team */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const hms = s => { s = Math.round(s || 0); return `${Math.floor(s / 3600)}:${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; };
const clock = t => { t = Math.max(0, Math.floor(t || 0)); const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = String(t % 60).padStart(2, '0'); return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`; };
const hours = s => `${((s || 0) / 3600).toFixed(2)} h`;
const fmtDate = ts => new Date(ts * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });

const ICON = {
  cctv: '<path d="M16.75 12h3.632a1 1 0 0 1 .894 1.447l-2.034 4.069a1 1 0 0 1-1.708.134l-2.124-2.97"/><path d="M17.106 9.053a1 1 0 0 1 .447 1.341l-3.106 6.211a1 1 0 0 1-1.342.447L3.61 12.3a2.92 2.92 0 0 1-1.3-3.91L3.69 5.6a2.92 2.92 0 0 1 3.92-1.3z"/><path d="M2 19h3.76a2 2 0 0 0 1.8-1.1L9 15"/><path d="M2 21v-4"/><path d="M7 9h.01"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
  map: '<path d="M14.106 5.553a2 2 0 0 0 1.788 0l3.659-1.83A1 1 0 0 1 21 4.619v12.764a1 1 0 0 1-.553.894l-4.553 2.277a2 2 0 0 1-1.788 0l-4.212-2.106a2 2 0 0 0-1.788 0l-3.659 1.83A1 1 0 0 1 3 19.381V6.618a1 1 0 0 1 .553-.894l4.553-2.277a2 2 0 0 1 1.788 0z"/><path d="M15 5.764v15"/><path d="M9 3.236v15"/>',
  review: '<rect width="8" height="4" x="8" y="2" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="m9 14 2 2 4-4"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  flag: '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" x2="4" y1="22" y2="15"/>',
  video: '<path d="m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.87a.5.5 0 0 0-.752-.432L16 10.5"/><rect x="2" y="6" width="14" height="12" rx="2"/>',
  logout: '<path d="m10 17-5-5 5-5"/><path d="M5 12h12"/><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/>',
  mail: '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  pencil: '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/>',
  trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
  plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  camera: '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/>',
  merge: '<path d="m8 6 4-4 4 4"/><path d="M12 2v10.3a4 4 0 0 1-1.172 2.872L4 22"/><path d="m20 22-5-5"/>',
  file: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>',
  refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
};
const icon = (n, cls = '') => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICON[n]}</svg>`;

const ZONE_COLORS = { work: '#eeb23e', break: '#5b8def', exclusion: '#e5534b' };
const ZONE_LABEL = { work: 'Work', break: 'Break', exclusion: 'Exclusion' };
const STATE_LABEL = { working: 'Working', idle: 'Non-working' };

let ME = null;
let cleanup = [];
const onLeave = fn => cleanup.push(fn);
const app = $('#app');

/* ---------- api ---------- */
async function api(path, opts = {}) {
  const o = { credentials: 'same-origin', ...opts };
  if (o.body && !(o.body instanceof FormData)) { o.body = JSON.stringify(o.body); o.headers = { 'Content-Type': 'application/json' }; }
  const r = await fetch(path, o);
  if (r.status === 401 && !path.startsWith('/api/auth')) { ME = null; location.hash = '#/login'; throw new Error('Sign in required'); }
  const data = r.headers.get('content-type')?.includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error(data?.detail || data || r.statusText);
  return data;
}

function toast(msg, err = false) {
  const t = document.createElement('div');
  t.className = 'toast' + (err ? ' err' : '');
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), err ? 6000 : 3500);
}

function modal(html, { narrow = false } = {}) {
  const m = document.createElement('div');
  m.className = 'modal';
  m.innerHTML = `<div class="card ${narrow ? 'narrow' : ''}">${html}</div>`;
  const close = () => { m.remove(); m.dispatchEvent(new Event('closed')); };
  m.addEventListener('mousedown', e => { if (e.target === m) close(); });
  $$('[data-close]', m).forEach(b => b.onclick = close);
  document.body.appendChild(m);
  m.close = close;
  return m;
}

function formModal(title, fieldsHtml, submit, label = 'Save') {
  const m = modal(`<h3>${esc(title)}</h3><form>${fieldsHtml}<div class="error" hidden></div>
    <div class="row" style="justify-content:flex-end"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary">${esc(label)}</button></div></form>`, { narrow: true });
  $('form', m).onsubmit = async e => {
    e.preventDefault();
    try { await submit(new FormData(e.target)); m.close(); }
    catch (err) { const el = $('.error', m); el.hidden = false; el.textContent = err.message; }
  };
  $('input,select', m)?.focus();
  return m;
}

/* ---------- layout ---------- */
const isManager = () => ME?.role === 'manager';

function shell(active, inner) {
  const link = (h, l) => `<a href="#/${h}" class="${active === h ? 'active' : ''}">${l}</a>`;
  return `<header class="topbar"><div class="wrap">
    <a class="logo" href="#/">${icon('cctv')}WORKWATCH</a>
    <nav class="nav">${link('dashboard', 'Dashboard')}${link('videos', 'Videos')}${link('review', 'Review queue')}${link('reports', 'Reports')}${isManager() ? link('team', 'Team') : ''}</nav>
    <div class="right"><span class="email">${esc(ME.email)}</span><span class="role-chip">${esc(ME.role)}</span>
      <button class="btn" id="signout">${icon('logout')}Sign out</button></div>
  </div></header><main class="wrap page">${inner}</main>`;
}

function mount(active, inner) {
  app.innerHTML = shell(active, inner);
  $('#signout').onclick = async () => { await api('/api/auth/logout', { method: 'POST' }); ME = null; location.hash = '#/'; };
}

/* ---------- router ---------- */
async function route() {
  cleanup.forEach(f => { try { f(); } catch { } });
  cleanup = [];
  $$('.modal').forEach(m => m.remove());
  const [, page = '', id] = location.hash.replace(/^#/, '').split('/');
  if (page === '' ) return landing();
  if (page === 'login' || page === 'signup') return authPage(page);
  if (!ME) {
    try { ME = await api('/api/auth/me'); } catch { location.hash = '#/login'; return; }
  }
  window.scrollTo(0, 0);
  try {
    if (page === 'dashboard') return await dashboard();
    if (page === 'videos' && id) return await videoPage(+id);
    if (page === 'videos') return await videosPage();
    if (page === 'review') return await reviewPage();
    if (page === 'reports') return await reportsPage();
    if (page === 'team' && isManager()) return await teamPage();
    if (page === 'demo') {
      const vids = await api('/api/videos');
      const demo = vids.find(v => v.is_demo) || vids[0];
      location.replace(demo ? `#/videos/${demo.id}` : '#/videos');
      return;
    }
    location.hash = '#/dashboard';
  } catch (e) { toast(e.message, true); }
}
window.addEventListener('hashchange', route);

/* ---------- landing + auth ---------- */
function landing() {
  const f = (i, t, d) => `<div class="feature">${icon(i)}<h3>${t}</h3><p>${d}</p></div>`;
  app.innerHTML = `<header class="topbar"><div class="wrap"><a class="logo" href="#/" style="font-weight:500">${icon('cctv')}WORKWATCH</a>
    <div class="right"><a class="btn" href="#/dashboard">Open dashboard</a></div></div></header>
  <main class="wrap">
    <section class="hero">
      <div class="eyebrow">YOLOv8 + OpenCV pipeline</div>
      <h1>Working and non-working hours, counted straight from your CCTV footage.</h1>
      <p>WorkWatch tracks every person in a video, decides working vs. non-working from the zones you draw, and turns it into a per-person timesheet with a human review step before the numbers go out.</p>
      <div class="row" style="gap:16px"><a class="btn primary lg" href="#/dashboard">Open the dashboard</a><a class="btn lg" href="#/demo">See the demo analysis</a></div>
    </section>
    <section class="features">
      ${f('upload', 'Upload footage', 'Drop in a video or a whole day of CCTV recordings. Your sample warehouse clip is already loaded as a demo.')}
      ${f('map', 'Draw work zones', 'Draw zones directly on the video frame — assembly lines, break areas, exclusion zones. The pipeline counts presence inside each one.')}
      ${f('review', 'Human review', 'Short or low-confidence segments are flagged automatically. Confirm or correct them in the review queue.')}
      ${f('download', 'Daily reports', 'Per-person working time, efficiency and flagged segments — downloadable as CSV and delivered to the manager.')}
    </section>
  </main>`;
}

function authPage(mode) {
  const signup = mode === 'signup';
  app.innerHTML = `<div class="auth"><a class="logo" href="#/">${icon('cctv')}WORKWATCH</a>
    <div class="card"><h2>${signup ? 'Create account' : 'Sign in'}</h2><p class="sub">Track working hours from your footage.</p>
    <form>
      ${signup ? '<div class="field"><label>Name</label><input type="text" name="name" placeholder="Your name"></div>' : ''}
      <div class="field"><label>Email</label><input type="email" name="email" placeholder="you@company.com" required autocomplete="email"></div>
      <div class="field"><label>Password</label><input type="password" name="password" placeholder="••••••••" required minlength="${signup ? 8 : 1}" autocomplete="${signup ? 'new-password' : 'current-password'}"></div>
      <div class="error" hidden></div>
      <button class="btn primary">${signup ? 'Create account' : 'Sign in'}</button>
    </form>
    <div class="switch">${signup ? 'Already have an account? <a href="#/login">Sign in</a>' : 'Don’t have an account? <a href="#/signup">Sign up</a>'}</div>
    ${signup ? '<p class="faint" style="font-size:13px;text-align:center;margin:14px 0 0">The first account becomes the manager. Later sign-ups join as viewers until a manager promotes them.</p>' : ''}
    </div></div>`;
  $('form').onsubmit = async e => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    try {
      await api(`/api/auth/${signup ? 'signup' : 'login'}`, { method: 'POST', body });
      ME = await api('/api/auth/me');
      location.hash = '#/dashboard';
    } catch (err) { const el = $('.error'); el.hidden = false; el.textContent = err.message; }
  };
}

/* ---------- dashboard ---------- */
function videoCard(v) {
  const s = v.summary;
  const prog = ['processing', 'queued'].includes(v.status) ? `<div class="progress"><div style="width:${Math.round(v.progress * 100)}%"></div></div>` : '';
  const status = { new: v.zones.length ? 'ready to run' : 'needs zones', queued: 'queued', processing: `analysing ${Math.round(v.progress * 100)}%`, done: 'analysed', error: 'error' }[v.status];
  return `<a class="vcard" href="#/videos/${v.id}">
    <div class="thumb" style="background-image:url('/api/videos/${v.id}/frame.jpg?t=${Math.min(1, (v.duration || 0) / 2)}')"><span class="badge ${v.status}">${status}</span></div>
    <div class="body"><div class="title">${esc(v.name)}${v.is_demo ? ' <span class="badge flag">demo</span>' : ''}</div>
      <div class="meta">${esc(v.camera_name || 'Upload')} · ${esc(v.recorded_on || '')} · ${clock(v.duration)}</div>
      ${s ? `<div class="sum"><span><b>${s.people}</b> people</span><span><b>${hours(s.working_s)}</b> working</span>${s.pending ? `<span style="color:var(--accent)"><b style="color:inherit">${s.pending}</b> to review</span>` : ''}</div>` : ''}
      ${prog}</div></a>`;
}

async function dashboard() {
  const [st, vids, people] = await Promise.all([api('/api/stats'), api('/api/videos'), api('/api/people')]);
  const stat = (l, v, i) => `<div class="stat"><div class="top"><span>${l}</span>${icon(i)}</div><div class="val">${v}</div></div>`;
  const max = Math.max(1, ...people.rows.map(r => r.observed_s));
  mount('dashboard', `
    <div class="page-head"><div><h1>Dashboard</h1><p>Working hours across your footage, at a glance.</p></div>
      <div class="actions"><a class="btn" href="#/review">Review flagged (${st.pending})</a></div></div>
    <div class="stats">
      ${stat('Working time tracked', `${(st.working_s / 3600).toFixed(2)} h`, 'clock')}
      ${stat('People tracked (latest runs)', st.people, 'users')}
      ${stat('Segments awaiting review', st.pending, 'flag')}
      ${stat('Videos in library', st.videos, 'video')}
    </div>
    ${people.rows.length ? `<h2>Working time by person</h2><div class="card" style="padding:8px 16px">
      <table class="t"><tr><th>Person</th><th>Footage</th><th></th><th class="n">Working</th><th class="n">Non-working</th><th class="n">Efficiency</th><th class="n">To review</th></tr>
      ${people.rows.map(r => `<tr><td>${esc(r.person)}</td><td class="muted">${esc(r.videos.join(', '))}</td>
        <td style="width:22%"><div class="bar" style="width:${Math.max(8, 100 * r.observed_s / max)}%"><div style="width:${r.efficiency}%"></div></div></td>
        <td class="n">${hms(r.working_s)}</td><td class="n">${hms(r.idle_s)}</td><td class="n">${r.efficiency}%</td><td class="n">${r.pending || '–'}</td></tr>`).join('')}
      </table></div>` : ''}
    <h2>Recent footage</h2>
    ${vids.length ? `<div class="vgrid">${vids.slice(0, 6).map(videoCard).join('')}</div>`
      : `<div class="empty">${isManager() ? 'No footage yet. <a href="#/videos">Upload a video</a> to get started.' : 'No footage yet. Ask a manager to upload footage.'}</div>`}
  `);
}

/* ---------- videos list + cameras ---------- */
async function videosPage() {
  const [vids, cams] = await Promise.all([api('/api/videos'), api('/api/cameras')]);
  mount('videos', `
    <div class="page-head"><div><h1>Videos</h1><p>Upload footage, draw zones, import pipeline results.</p></div>
      <div class="actions">${isManager() ? `<button class="btn primary" id="upload">${icon('upload')}Upload video</button>` : ''}</div></div>
    ${vids.length ? `<div class="vgrid">${vids.map(videoCard).join('')}</div>`
      : '<div class="empty">No footage yet. Upload a video, then draw work zones on it and run the YOLOv8 pipeline.</div>'}
    <h2>CCTV cameras</h2>
    <div class="grid2">
      <div class="card">
        <div class="row" style="margin-bottom:6px"><h3 style="margin:0">Connected cameras</h3><span class="spacer"></span>
          ${isManager() ? `<button class="btn sm" id="addcam">${icon('plus')}Add camera</button>` : ''}</div>
        ${cams.length ? cams.map(c => `<div class="cam"><div><div style="font-weight:600">${esc(c.name)} <span class="faint mono" style="font-size:12px">#${c.id}</span></div>
            <div class="url">${esc(c.rtsp_url || 'no stream URL — inbox folder only')}</div>
            <div class="faint" style="font-size:12.5px">${c.zones.length} zone(s) · inbox <code>data/inbox/${c.id}/</code></div></div>
          <div class="row">${c.rtsp_url ? `<button class="btn sm" data-snap="${c.id}">${icon('camera')}Snapshot</button>` : ''}
            ${isManager() ? `<button class="btn sm" data-czones="${c.id}">${icon('map')}Zones</button>
            ${c.rtsp_url ? `<button class="btn sm" data-rec="${c.id}">${icon('video')}Record</button>` : ''}
            <button class="btn sm danger" data-delcam="${c.id}">${icon('trash')}</button>` : ''}</div></div>`).join('')
      : '<p class="muted" style="margin:8px 0 0">No cameras yet. Add an RTSP/HTTP stream from your NVR or IP camera.</p>'}
      </div>
      <div class="card"><h3>How CCTV footage gets in</h3>
        <p class="muted" style="margin-top:0">Each camera has an inbox folder. Anything dropped there is imported by the daily job, inherits the camera's zones, and is analysed automatically. Continuous recording into the inbox with ffmpeg:</p>
        <pre>ffmpeg -rtsp_transport tcp -i "rtsp://user:pass@cam/stream" \\
  -c copy -f segment -segment_time 3600 -strftime 1 \\
  data/inbox/&lt;camera id&gt;/%Y-%m-%d_%H-%M.mp4</pre>
        <p class="muted" style="margin-bottom:0">Or use <b>Record</b> for an on-demand clip. The daily job runs <code>python -m workwatch daily</code>.</p></div>
    </div>`);

  $('#upload')?.addEventListener('click', () => uploadModal(cams));
  $('#addcam')?.addEventListener('click', () => formModal('Add camera', `
      <div class="field"><label>Name</label><input type="text" name="name" placeholder="Assembly line – cam 1" required></div>
      <div class="field"><label>Stream URL (optional)</label><input type="text" name="rtsp_url" placeholder="rtsp://user:pass@192.168.1.20:554/stream1"></div>
      <p class="faint" style="font-size:13px;margin-top:-6px">Leave empty if footage arrives as exported files in the camera's inbox folder.</p>`,
    async fd => { await api('/api/cameras', { method: 'POST', body: Object.fromEntries(fd) }); route(); }, 'Add camera'));
  $$('[data-snap]').forEach(b => b.onclick = () => {
    const m = modal(`<h3>Live snapshot</h3><p class="muted">Grabbing a frame from the stream…</p><img src="/api/cameras/${b.dataset.snap}/snapshot.jpg?${Date.now()}" style="width:100%;border-radius:8px"><div class="row" style="justify-content:flex-end;margin-top:14px"><button class="btn" data-close>Close</button></div>`);
    const img = $('img', m); img.onload = () => $('p', m).remove(); img.onerror = () => { $('p', m).textContent = 'Could not reach the camera stream.'; img.remove(); };
  });
  $$('[data-czones]').forEach(b => b.onclick = () => cameraZones(cams.find(c => c.id === +b.dataset.czones), vids));
  $$('[data-rec]').forEach(b => b.onclick = () => formModal('Record from camera', `
      <div class="field"><label>Minutes</label><input type="number" name="minutes" value="5" min="0.5" step="0.5" required></div>
      <label class="row muted"><input type="checkbox" name="analyze" checked> Analyse when done (needs camera zones)</label><br>`,
    async fd => { const r = await api(`/api/cameras/${b.dataset.rec}/record`, { method: 'POST', body: { minutes: +fd.get('minutes'), analyze: !!fd.get('analyze') } }); toast(r.message); }, 'Start recording'));
  $$('[data-delcam]').forEach(b => b.onclick = async () => {
    if (!confirm('Remove this camera? Its recorded videos stay in the library.')) return;
    await api(`/api/cameras/${b.dataset.delcam}`, { method: 'DELETE' }); route();
  });
  if (vids.some(v => ['queued', 'processing'].includes(v.status))) {
    const t = setTimeout(route, 2500); onLeave(() => clearTimeout(t));
  }
}

function uploadModal(cams) {
  const today = new Date().toISOString().slice(0, 10);
  const m = modal(`<h3>Upload footage</h3><form>
    <div class="field"><label>Video file</label><input type="file" name="file" accept="video/*,.mkv,.ts" required></div>
    <div class="field"><label>Name</label><input type="text" name="name" placeholder="Defaults to the file name"></div>
    <div class="grid2" style="gap:12px"><div class="field"><label>Recorded on</label><input type="date" name="recorded_on" value="${today}"></div>
    <div class="field"><label>Camera</label><select name="camera_id"><option value="">— none —</option>${cams.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></div></div>
    <p class="faint" style="font-size:13px;margin-top:-4px">Picking a camera copies its zones onto the video.</p>
    <div class="progress" hidden><div style="width:0"></div></div><div class="error" hidden></div>
    <div class="row" style="justify-content:flex-end;margin-top:12px"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary">${icon('upload')}Upload</button></div></form>`, { narrow: true });
  $('form', m).onsubmit = e => {
    e.preventDefault();
    const xhr = new XMLHttpRequest();
    const bar = $('.progress', m); bar.hidden = false;
    xhr.upload.onprogress = ev => { $('div', bar).style.width = `${100 * ev.loaded / ev.total}%`; };
    xhr.onload = () => {
      if (xhr.status >= 300) { const el = $('.error', m); el.hidden = false; el.textContent = JSON.parse(xhr.responseText).detail || 'Upload failed'; return; }
      const v = JSON.parse(xhr.responseText); m.close(); location.hash = `#/videos/${v.id}`;
    };
    xhr.open('POST', '/api/videos'); xhr.send(new FormData(e.target));
    $('button.primary', m).disabled = true;
  };
}

function cameraZones(cam, vids) {
  const latest = vids.find(v => v.camera_id === cam.id);
  const src = cam.rtsp_url ? `/api/cameras/${cam.id}/snapshot.jpg?${Date.now()}` : latest ? `/api/videos/${latest.id}/frame.jpg` : null;
  if (!src) return toast('Add a stream URL or import a clip for this camera first, so there is a frame to draw on.', true);
  const zones = structuredClone(cam.zones);
  const m = modal(`<h3>Zones — ${esc(cam.name)}</h3><p class="muted" style="margin-top:-6px">New footage from this camera inherits these zones.</p>
    <div class="stage editing"><img class="bg"></div><div class="toolbar" id="ztools"></div><div class="zone-list"></div>
    <div class="row" style="justify-content:flex-end;margin-top:14px"><button class="btn" data-close>Cancel</button><button class="btn primary" id="savez">Save zones</button></div>`);
  const img = $('img', m);
  img.onerror = () => { if (latest && !img.src.includes('/videos/')) img.src = `/api/videos/${latest.id}/frame.jpg`; else toast('Could not load a frame for this camera.', true); };
  img.src = src;
  const ov = new Overlay($('.stage', m), img, { zones });
  zoneTools(ov, $('#ztools', m), $('.zone-list', m));
  ov.setEditing(true);
  m.addEventListener('closed', () => ov.destroy());
  $('#savez', m).onclick = async () => {
    try { await api(`/api/cameras/${cam.id}`, { method: 'PATCH', body: { zones: ov.zones } }); m.close(); toast('Camera zones saved'); route(); }
    catch (e) { toast(e.message, true); }
  };
}

/* ---------- zone + box overlay ---------- */
class Overlay {
  constructor(stage, media, { zones = [], onChange = () => { } } = {}) {
    Object.assign(this, { stage, media, zones, onChange, editing: false, draft: null, draftType: 'work', tracks: null, labels: {}, highlight: null, showBoxes: true, mouse: null, drag: null });
    this.canvas = document.createElement('canvas');
    this.canvas.style.pointerEvents = 'none';
    stage.appendChild(this.canvas);
    this.ctx = this.canvas.getContext('2d');
    this.ro = new ResizeObserver(() => this.resize()); this.ro.observe(media);
    this.canvas.addEventListener('mousedown', e => this.down(e));
    this.canvas.addEventListener('dblclick', e => { e.preventDefault(); this.finish(); });
    this.canvas.addEventListener('contextmenu', e => { e.preventDefault(); this.draft = null; this.draw(); });
    this._move = e => this.move(e);
    this._up = () => { if (this.drag) { this.drag = null; this.changed(); } };
    this._key = e => {
      if (!this.editing || ['INPUT', 'SELECT'].includes(document.activeElement?.tagName)) return;
      if (e.key === 'Escape') { this.draft = null; this.draw(); }
      if (e.key === 'Enter') this.finish();
      if (e.key === 'Backspace' && this.draft) { this.draft.points.pop(); if (!this.draft.points.length) this.draft = null; this.draw(); e.preventDefault(); }
    };
    window.addEventListener('mousemove', this._move); window.addEventListener('mouseup', this._up); window.addEventListener('keydown', this._key);
    const loop = () => { if (this.dead) return; if (this.media.tagName === 'VIDEO' && !this.media.paused) this.draw(); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
    if (media.tagName === 'VIDEO') media.addEventListener('seeked', () => this.draw());
    else media.addEventListener('load', () => this.resize());
  }
  destroy() { this.dead = true; this.ro.disconnect(); window.removeEventListener('mousemove', this._move); window.removeEventListener('mouseup', this._up); window.removeEventListener('keydown', this._key); }
  setEditing(on) { this.editing = on; this.draft = null; this.canvas.style.pointerEvents = on ? 'auto' : 'none'; this.stage.classList.toggle('editing', on); this.draw(); }
  changed() { this.onChange(this.zones); this.draw(); }
  resize() {
    const r = this.media.getBoundingClientRect(), dpr = devicePixelRatio || 1;
    this.w = r.width; this.h = r.height;
    this.canvas.width = r.width * dpr; this.canvas.height = r.height * dpr;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.draw();
  }
  pos(e) { const r = this.canvas.getBoundingClientRect(); return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))]; }
  near(a, b, px = 10) { return Math.hypot((a[0] - b[0]) * this.w, (a[1] - b[1]) * this.h) < px; }
  down(e) {
    if (!this.editing || e.button !== 0) return;
    const p = this.pos(e);
    if (!this.draft) {
      for (let zi = this.zones.length - 1; zi >= 0; zi--) {
        const pi = this.zones[zi].points.findIndex(q => this.near(p, q));
        if (pi >= 0) { this.drag = { zi, pi }; return; }
      }
      this.draft = { type: this.draftType, points: [p] };
    } else if (this.draft.points.length >= 3 && this.near(p, this.draft.points[0], 12)) {
      return this.finish();
    } else this.draft.points.push(p);
    this.draw();
  }
  move(e) {
    if (!this.editing) return;
    const p = this.pos(e);
    if (this.drag) { this.zones[this.drag.zi].points[this.drag.pi] = p; this.draw(); return; }
    this.mouse = p; if (this.draft) this.draw();
  }
  finish() {
    if (!this.draft || this.draft.points.length < 3) return;
    const n = this.zones.filter(z => z.type === this.draft.type).length + 1;
    this.zones.push({ name: `${ZONE_LABEL[this.draft.type]} ${n}`, type: this.draft.type, points: this.draft.points });
    this.draft = null; this.changed();
  }
  boxesAt(t) {
    const out = [];
    for (const [tid, s] of Object.entries(this.tracks || {})) {
      let lo = 0, hi = s.length - 1;
      if (hi < 0 || t < s[0][0] - 0.3 || t > s[hi][0] + 0.3) continue;
      while (lo < hi) { const mid = (lo + hi) >> 1; if (s[mid][0] < t) lo = mid + 1; else hi = mid; }
      const c = lo > 0 && Math.abs(s[lo - 1][0] - t) < Math.abs(s[lo][0] - t) ? s[lo - 1] : s[lo];
      if (Math.abs(c[0] - t) <= 0.3) out.push([+tid, c]);
    }
    return out;
  }
  draw() {
    const { ctx, w, h } = this;
    if (!w) return;
    ctx.clearRect(0, 0, w, h);
    const poly = (pts, close) => { ctx.beginPath(); pts.forEach(([x, y], i) => i ? ctx.lineTo(x * w, y * h) : ctx.moveTo(x * w, y * h)); if (close) ctx.closePath(); };
    ctx.font = '600 12px "Space Grotesk", sans-serif';
    for (const z of this.zones) {
      const col = ZONE_COLORS[z.type];
      poly(z.points, true);
      ctx.fillStyle = col + '2a'; ctx.fill();
      ctx.lineWidth = 2; ctx.strokeStyle = col; ctx.stroke();
      const [x, y] = z.points.reduce((a, p) => (p[1] < a[1] ? p : a));
      const tw = ctx.measureText(z.name).width + 10;
      ctx.fillStyle = col; ctx.fillRect(x * w, y * h - 18, tw, 18);
      ctx.fillStyle = '#111'; ctx.fillText(z.name, x * w + 5, y * h - 5);
      if (this.editing) z.points.forEach(([px, py]) => { ctx.fillStyle = '#fff'; ctx.fillRect(px * w - 4, py * h - 4, 8, 8); });
    }
    if (this.draft) {
      const col = ZONE_COLORS[this.draft.type];
      poly(this.mouse ? [...this.draft.points, this.mouse] : this.draft.points, false);
      ctx.setLineDash([6, 4]); ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.stroke(); ctx.setLineDash([]);
      this.draft.points.forEach(([px, py], i) => { ctx.beginPath(); ctx.arc(px * w, py * h, i ? 4 : 7, 0, 7); ctx.fillStyle = i ? col : '#fff'; ctx.fill(); });
    }
    if (this.tracks && this.showBoxes && this.media.tagName === 'VIDEO') {
      for (const [tid, [, x1, y1, x2, y2, code]] of this.boxesAt(this.media.currentTime)) {
        const dim = this.highlight != null && this.highlight !== tid;
        const col = code === 1 ? '#eeb23e' : code === 2 ? '#e5534b' : '#9aa6b5';
        ctx.globalAlpha = dim ? 0.25 : 1;
        ctx.lineWidth = this.highlight === tid ? 3 : 2; ctx.strokeStyle = col;
        ctx.strokeRect(x1 * w, y1 * h, (x2 - x1) * w, (y2 - y1) * h);
        const label = `${this.labels[tid] || 'Worker ' + tid} · ${code === 1 ? 'working' : code === 2 ? 'excluded' : 'idle'}`;
        const tw = ctx.measureText(label).width + 10;
        ctx.fillStyle = col; ctx.fillRect(x1 * w, y1 * h - 18, tw, 18);
        ctx.fillStyle = '#111'; ctx.fillText(label, x1 * w + 5, y1 * h - 5);
        ctx.beginPath(); ctx.arc((x1 + x2) / 2 * w, y2 * h, 3.5, 0, 7); ctx.fillStyle = col; ctx.fill();
        ctx.globalAlpha = 1;
      }
    }
  }
}

function zoneTools(ov, bar, list) {
  bar.innerHTML = `<span class="muted" style="font-size:13px">Draw:</span>
    ${Object.keys(ZONE_LABEL).map(t => `<button class="btn sm ${t === ov.draftType ? 'on' : ''}" data-type="${t}"><span class="dot" style="background:${ZONE_COLORS[t]}"></span>${ZONE_LABEL[t]} zone</button>`).join('')}
    <span class="faint" style="font-size:12.5px">Click to add points · click the first point or press Enter to close · drag corners to adjust · Esc cancels</span>`;
  $$('[data-type]', bar).forEach(b => b.onclick = () => {
    ov.draftType = b.dataset.type; if (ov.draft) ov.draft.type = b.dataset.type;
    $$('[data-type]', bar).forEach(x => x.classList.toggle('on', x === b)); ov.draw();
  });
  const renderList = () => {
    list.innerHTML = ov.zones.length ? ov.zones.map((z, i) => `<div class="zone-item"><span class="dot" style="background:${ZONE_COLORS[z.type]}"></span>
      <input type="text" value="${esc(z.name)}" data-i="${i}" data-k="name"><select data-i="${i}" data-k="type">${Object.keys(ZONE_LABEL).map(t => `<option value="${t}" ${t === z.type ? 'selected' : ''}>${ZONE_LABEL[t]}</option>`).join('')}</select>
      <button class="btn sm danger" data-del="${i}">${icon('trash')}</button></div>`).join('')
      : '<p class="faint" style="margin:0;font-size:13px">No zones yet. Pick a zone type and click on the frame.</p>';
    $$('[data-k]', list).forEach(el => el.oninput = () => { ov.zones[el.dataset.i][el.dataset.k] = el.value; ov.draw(); if (el.tagName === 'SELECT') renderList(); });
    $$('[data-del]', list).forEach(b => b.onclick = () => { ov.zones.splice(+b.dataset.del, 1); ov.changed(); });
  };
  const prev = ov.onChange;
  ov.onChange = z => { prev(z); renderList(); };
  renderList();
}

/* ---------- video detail ---------- */
async function videoPage(id) {
  const data = await api(`/api/videos/${id}/results`);
  const v = data.video;
  const people = data.people;
  const busy = ['queued', 'processing'].includes(v.status);
  const pending = people.reduce((a, p) => a + p.pending, 0);
  const statusLine = {
    new: v.zones.some(z => z.type === 'work') ? 'Zones are set — run the pipeline.' : 'Draw at least one work zone on the frame, then run the pipeline.',
    queued: 'Queued for analysis…', processing: `Analysing… ${Math.round(v.progress * 100)}%`,
    done: `Analysed ${data.run ? fmtDate(data.run.created_at) : ''}${data.run?.stats?.processing_s ? ` in ${data.run.stats.processing_s}s` : ''}`, error: `Pipeline error: ${v.error}`,
  }[v.status];

  mount('videos', `
    <div class="page-head"><div><p class="faint" style="margin:0 0 4px"><a href="#/videos" style="text-decoration:none">← Videos</a></p>
      <h1>${esc(v.name)}</h1><p>${esc(v.camera_name || 'Uploaded footage')} · ${esc(v.recorded_on)} · ${clock(v.duration)} · ${v.width}×${v.height} @ ${Math.round(v.fps)} fps</p></div>
      ${isManager() ? `<div class="actions">
        <button class="btn" id="rename">${icon('pencil')}Rename</button>
        <button class="btn" id="import">${icon('file')}Import results</button>
        <button class="btn danger" id="delete">${icon('trash')}Delete</button>
        <button class="btn primary" id="run" ${busy ? 'disabled' : ''}>${icon(data.run ? 'refresh' : 'play')}${data.run ? 'Re-run pipeline' : 'Run pipeline'}</button></div>` : ''}
    </div>
    <div class="banner ${v.status === 'done' ? 'ok' : ''}" style="align-items:center">${icon(v.status === 'done' ? 'check' : v.status === 'error' ? 'flag' : 'clock')}
      <div style="flex:1"><b>${esc(statusLine)}</b>${v.status === 'done' && pending ? ` <a href="#/review">${pending} flagged segment(s) need review.</a>` : ''}
      ${busy ? `<div class="progress"><div style="width:${Math.round(v.progress * 100)}%"></div></div>` : ''}</div></div>
    <div class="two">
      <div>
        <div class="stage" id="stage"><video id="vid" src="/api/videos/${id}/stream" poster="/api/videos/${id}/frame.jpg" controls preload="auto" playsinline muted></video></div>
        <div class="toolbar">
          ${isManager() ? `<button class="btn sm" id="editz">${icon('map')}Edit zones</button><button class="btn sm primary" id="savez" hidden>Save zones</button>` : ''}
          <label class="row muted" style="font-size:13px;gap:6px"><input type="checkbox" id="boxes" checked ${data.run ? '' : 'disabled'}> Show tracked people</label>
          <span class="spacer"></span>
          <div class="legend"><span><i class="dot" style="background:var(--working)"></i>Working</span><span><i class="dot" style="background:var(--idle)"></i>Non-working</span><span><i class="dot" style="background:var(--break)"></i>Break zone</span><span><i class="dot" style="background:var(--exclusion)"></i>Exclusion</span></div>
        </div>
        <div id="ztools" class="toolbar" hidden></div>
        <div id="zlist" class="zone-list" hidden></div>
      </div>
      <div class="card" style="padding:16px">
        <h3>People <span class="faint" style="font-weight:400">(${people.length})</span></h3>
        ${people.length ? `<div class="people">${people.map(p => personCard(p, data.run.id)).join('')}</div>`
      : `<p class="muted" style="margin:0">${data.run ? 'Nobody was tracked inside the frame.' : 'Run the pipeline to track people.'}</p>`}
      </div>
    </div>
    ${people.length ? `<h2>Timeline</h2><div class="timeline">${timelineHTML(people, v.duration)}</div>` : ''}
  `);

  const vid = $('#vid');
  const ov = new Overlay($('#stage'), vid, { zones: structuredClone(v.zones) });
  onLeave(() => ov.destroy());
  if (data.run) {
    api(`/api/runs/${data.run.id}/tracks`).then(t => { ov.tracks = t; ov.draw(); });
    people.forEach(p => p.track_ids.forEach(t => { ov.labels[t] = p.label; }));
  }
  $('#boxes').onchange = e => { ov.showBoxes = e.target.checked; ov.draw(); };

  // timeline <-> player
  const heads = $$('.tl-head');
  const tick = () => { const pct = 100 * vid.currentTime / (vid.duration || v.duration || 1); heads.forEach(h => h.style.left = pct + '%'); };
  vid.addEventListener('timeupdate', tick);
  $$('[data-seek]').forEach(el => el.onclick = () => { vid.currentTime = +el.dataset.seek; vid.play(); $('#stage').scrollIntoView({ behavior: 'smooth', block: 'center' }); });
  $$('.person').forEach(el => {
    el.onmouseenter = () => { ov.highlight = +el.dataset.track; ov.draw(); };
    el.onmouseleave = () => { ov.highlight = null; ov.draw(); };
  });

  if (isManager()) {
    let dirty = false;
    ov.onChange = () => { dirty = true; };
    zoneTools(ov, $('#ztools'), $('#zlist'));
    $('#editz').onclick = () => {
      const on = !ov.editing;
      if (on) vid.pause();
      ov.setEditing(on);
      $('#ztools').hidden = $('#zlist').hidden = !on; $('#savez').hidden = !on;
      $('#editz').classList.toggle('on', on);
      $('#editz').lastChild.textContent = on ? 'Done editing' : 'Edit zones';
    };
    $('#savez').onclick = async () => {
      try { await api(`/api/videos/${id}/zones`, { method: 'PUT', body: ov.zones }); dirty = false; toast(data.run ? 'Zones saved — re-run the pipeline to apply them' : 'Zones saved'); }
      catch (e) { toast(e.message, true); }
    };
    $('#run').onclick = async () => {
      try {
        if (dirty) await api(`/api/videos/${id}/zones`, { method: 'PUT', body: ov.zones });
        await api(`/api/videos/${id}/analyze`, { method: 'POST' }); toast('Pipeline queued'); route();
      } catch (e) { toast(e.message, true); }
    };
    $('#rename').onclick = () => formModal('Rename video', `<div class="field"><label>Name</label><input type="text" name="name" value="${esc(v.name)}" required></div>
      <div class="field"><label>Recorded on</label><input type="date" name="recorded_on" value="${esc(v.recorded_on)}"></div>`,
      async fd => { await api(`/api/videos/${id}`, { method: 'PATCH', body: Object.fromEntries(fd) }); route(); });
    $('#delete').onclick = async () => {
      if (!confirm(`Delete “${v.name}” and its analysis? This can't be undone.`)) return;
      await api(`/api/videos/${id}`, { method: 'DELETE' }); location.hash = '#/videos';
    };
    $('#import').onclick = () => formModal('Import pipeline results', `<p class="muted" style="margin-top:0">Upload a <code>results.json</code> produced by<br><code>python -m workwatch analyze video.mp4 --zones zones.json</code> on another machine.</p>
      <div class="field"><input type="file" name="file" accept=".json,application/json" required></div>`,
      async fd => { await api(`/api/videos/${id}/import-results`, { method: 'POST', body: fd }); toast('Results imported'); route(); }, 'Import');
    $$('[data-rename]').forEach(b => b.onclick = () => {
      const p = people.find(x => x.id === +b.dataset.rename);
      formModal('Name this person', `<div class="field"><label>Name or badge</label><input type="text" name="label" value="${esc(p.label)}" required></div>
        <p class="faint" style="font-size:13px;margin-top:-6px">Using the same name on other videos combines their hours in reports.</p>`,
        async fd => { await api(`/api/persons/${p.id}`, { method: 'PATCH', body: { label: fd.get('label') } }); route(); });
    });
    $$('[data-merge]').forEach(b => b.onclick = () => {
      const p = people.find(x => x.id === +b.dataset.merge);
      formModal(`Merge ${p.label} into…`, `<p class="muted" style="margin-top:0">Use when the tracker gave one person two IDs (e.g. after walking behind a machine). ${esc(p.label)}'s segments move to the person you pick.</p>
        <div class="field"><select name="into">${people.filter(x => x.id !== p.id).map(x => `<option value="${x.id}">${esc(x.label)} (${hms(x.working_s + x.idle_s)})</option>`).join('')}</select></div>`,
        async fd => { await api(`/api/persons/${p.id}/merge`, { method: 'POST', body: { into: +fd.get('into') } }); route(); }, 'Merge');
    });
  }
  if (busy) { const t = setTimeout(route, 2000); onLeave(() => clearTimeout(t)); }
}

function personCard(p, runId) {
  return `<div class="person" data-track="${p.track_id}">
    ${p.thumb ? `<img src="/api/runs/${runId}/thumbs/${esc(p.thumb)}" alt="">` : '<div class="ph"></div>'}
    <div><div class="name">${esc(p.label)}${isManager() ? `<button title="Rename" data-rename="${p.id}">${icon('pencil', '').replace('<svg', '<svg width="13" height="13"')}</button><button title="Merge into another person" data-merge="${p.id}">${icon('merge').replace('<svg', '<svg width="13" height="13"')}</button>` : ''}</div>
      <div class="nums"><span><b>${hms(p.working_s)}</b> working</span><span>${hms(p.idle_s)} idle</span><span>${p.efficiency}%</span></div>
      <div class="nums" style="margin-top:2px"><span>seen ${clock(p.first_seen)}–${clock(p.last_seen)}</span>${p.pending ? `<span style="color:var(--accent)">${p.pending} to review</span>` : ''}</div>
    </div></div>`;
}

function timelineHTML(people, duration) {
  const D = duration || Math.max(...people.map(p => p.last_seen)) || 1;
  const ticks = [0, .25, .5, .75, 1].map(f => `<span>${clock(D * f)}</span>`).join('');
  return `<div class="tl-axis"><span></span><div class="ticks">${ticks}</div><span style="text-align:right">working / idle</span></div>` +
    people.map(p => `<div class="tl-row"><div class="lbl">${esc(p.label)}</div><div class="tl-track">
      ${p.segments.map(s => `<div class="tl-seg ${s.effective_state} ${s.review_status === 'pending' ? 'flagged' : ''}" data-seek="${s.start}"
        style="left:${100 * s.start / D}%;width:${100 * (s.end - s.start) / D}%"
        title="${STATE_LABEL[s.effective_state]}${s.zone ? ' · ' + esc(s.zone) : ''} · ${clock(s.start)}–${clock(s.end)} (${(s.end - s.start).toFixed(1)}s)${s.flag_reason ? '\n⚑ ' + esc(s.flag_reason) : ''}${s.review_status === 'corrected' ? '\n✓ corrected by reviewer' : s.review_status === 'confirmed' ? '\n✓ confirmed' : ''}"></div>`).join('')}
      <div class="tl-head" style="left:0"></div></div>
      <div class="tot">${hms(p.working_s)} / ${hms(p.idle_s)}</div></div>`).join('');
}

/* ---------- review queue ---------- */
let reviewTab = 'pending';
async function reviewPage() {
  const items = await api(`/api/review?status=${reviewTab}`);
  mount('review', `
    <div class="page-head"><div><h1>Review queue</h1><p>Short or low-confidence segments the pipeline flagged. Confirm them or correct the state — totals update immediately.</p></div></div>
    <div class="tabs"><button data-tab="pending" class="${reviewTab === 'pending' ? 'active' : ''}">Pending</button><button data-tab="done" class="${reviewTab === 'done' ? 'active' : ''}">Reviewed</button></div>
    ${items.length ? items.map(reviewItem).join('') : `<div class="empty">${reviewTab === 'pending' ? 'Nothing to review — the queue is clear.' : 'No reviewed segments yet.'}</div>`}`);
  $$('[data-tab]').forEach(b => b.onclick = () => { reviewTab = b.dataset.tab; route(); });
  $$('[data-play]').forEach(b => b.onclick = () => playSegment(items.find(s => s.id === +b.dataset.play)));
  wireReviewActions(document);
}

function reviewActs(s) {
  const st = s.state, other = st === 'working' ? 'idle' : 'working';
  if (!isManager()) return '';
  return s.review_status === 'pending'
    ? `<button class="btn sm primary" data-act="set_state" data-state="${st}" data-sid="${s.id}">${icon('check')}Confirm ${STATE_LABEL[st].toLowerCase()}</button>
       <button class="btn sm" data-act="set_state" data-state="${other}" data-sid="${s.id}">Mark ${STATE_LABEL[other].toLowerCase()}</button>`
    : `<button class="btn sm" data-act="reopen" data-sid="${s.id}">Reopen</button>`;
}

function reviewItem(s) {
  const st = s.state;
  const acts = reviewActs(s);
  const outcome = s.review_status === 'corrected' ? `<span class="badge working">corrected → ${STATE_LABEL[s.reviewed_state]}</span>` : s.review_status === 'confirmed' ? '<span class="badge done">confirmed</span>' : '';
  return `<div class="rv">
    ${s.thumb ? `<img src="/api/runs/${s.run_id}/thumbs/${esc(s.thumb)}" alt="">` : '<div class="ph"></div>'}
    <div><div class="title">${esc(s.label)} <span class="faint" style="font-weight:400">· ${esc(s.video_name)}</span> ${outcome}</div>
      <div class="sub">${clock(s.start)}–${clock(s.end)} (${(s.end - s.start).toFixed(1)}s) · detected <b class="badge ${st}">${STATE_LABEL[st]}</b>${s.zone ? ` in ${esc(s.zone)}` : ''} · confidence ${(s.confidence ?? 0).toFixed(2)}</div>
      <div class="reason">⚑ ${esc(s.flag_reason || '')}${s.reviewed_by ? ` <span class="faint">· reviewed by ${esc(s.reviewed_by)}</span>` : ''}</div></div>
    <div class="acts"><button class="btn sm" data-play="${s.id}">${icon('play')}Watch</button>${acts}</div></div>`;
}

function wireReviewActions(root, after = route) {
  $$('[data-act]', root).forEach(b => b.onclick = async () => {
    try { await api(`/api/segments/${b.dataset.sid}/review`, { method: 'POST', body: { action: b.dataset.act, state: b.dataset.state } }); after(); }
    catch (e) { toast(e.message, true); }
  });
}

async function playSegment(s) {
  const pad = 1.5, from = Math.max(0, s.start - pad), to = s.end + pad;
  const m = modal(`<div class="row" style="margin-bottom:12px"><h3 style="margin:0">${esc(s.label)} · ${clock(s.start)}–${clock(s.end)}</h3><span class="spacer"></span><button class="btn sm" data-close>Close</button></div>
    <div class="stage"><video src="/api/videos/${s.video_id}/stream#t=${from}" autoplay muted playsinline controls></video></div>
    <p class="muted" style="font-size:13.5px">Plays the flagged segment with ${pad}s either side, on loop. The highlighted box is this person; detected state: <b>${STATE_LABEL[s.state]}</b>${s.zone ? ` in ${esc(s.zone)}` : ''}.</p>
    <div class="row" style="justify-content:flex-end">${reviewActs(s)}</div>`);
  const vid = $('video', m);
  const [vdata, tracks] = await Promise.all([api(`/api/videos/${s.video_id}`), api(`/api/runs/${s.run_id}/tracks`)]);
  const ov = new Overlay($('.stage', m), vid, { zones: vdata.zones });
  ov.tracks = { [s.track_id]: tracks[s.track_id] || [] };
  ov.labels[s.track_id] = s.label; ov.highlight = s.track_id;
  vid.addEventListener('timeupdate', () => { if (vid.currentTime > to) vid.currentTime = from; });
  m.addEventListener('closed', () => ov.destroy());
  wireReviewActions(m, () => { m.close(); route(); });
}

/* ---------- reports ---------- */
async function reportsPage() {
  const [reps, st] = await Promise.all([api('/api/reports'), api('/api/stats')]);
  const today = new Date().toISOString().slice(0, 10);
  const banner = st.email_configured
    ? `<div class="banner ok">${icon('mail')}<div><b>Email delivery is on:</b> reports can be mailed to ${esc(st.manager_emails.join(', ') || 'you')}.${st.daily_run_at ? ` The daily job runs at <b>${esc(st.daily_run_at)}</b> and emails the timesheet automatically.` : ' Set <code>WW_DAILY_RUN_AT</code> in <code>.env</code> to send it automatically every day.'}</div></div>`
    : `<div class="banner">${icon('mail')}<div><b>Email delivery is one step away:</b> once SMTP is configured for this app (<code>SMTP_HOST</code>, <code>SMTP_FROM</code>, <code>MANAGER_EMAILS</code> in <code>.env</code>), the “Email this report” button activates and daily reports can be mailed to the manager automatically.</div></div>`;
  mount('reports', `
    <div class="page-head"><div><h1>Reports</h1><p>Generate the daily timesheet from the latest analysis, download it as CSV, and keep a history here.</p></div></div>
    ${banner}
    ${isManager() ? `<div class="card" style="margin-bottom:26px"><form class="row" id="gen" style="align-items:flex-end;gap:14px">
      <div class="field" style="margin:0;max-width:200px"><label>Footage recorded on</label><input type="date" name="date" value="${today}"></div>
      <button class="btn primary" name="mode" value="date">Generate daily timesheet</button>
      <button class="btn" name="mode" value="all" type="submit">Generate from all footage</button>
      <span class="spacer"></span>
      <button class="btn" type="button" id="daily" title="Ingest inbox footage, analyse anything new, build the report and email it">${icon('refresh')}Run daily job now</button>
    </form></div>` : ''}
    ${reps.length ? reps.map(reportCard).join('') : '<div class="empty">No reports yet. Generate the first one from analyzed footage above.</div>'}`);

  const form = $('#gen');
  if (form) form.onsubmit = async e => {
    e.preventDefault();
    const mode = e.submitter?.value;
    try { await api('/api/reports', { method: 'POST', body: mode === 'all' ? {} : { date: form.date.value } }); toast('Report generated'); route(); }
    catch (err) { toast(err.message, true); }
  };
  $('#daily')?.addEventListener('click', async () => {
    const r = await api('/api/daily/run', { method: 'POST', body: { date: form.date.value } });
    toast(r.message + ' — refresh in a moment to see the report.');
  });
  $$('[data-email]').forEach(b => b.onclick = async () => {
    try { const r = await api(`/api/reports/${b.dataset.email}/email`, { method: 'POST', body: {} }); toast(`Emailed to ${[].concat(r.to).join(', ')}`); route(); }
    catch (e) { toast(e.message, true); }
  });
  $$('[data-delrep]').forEach(b => b.onclick = async () => { if (confirm('Delete this report?')) { await api(`/api/reports/${b.dataset.delrep}`, { method: 'DELETE' }); route(); } });
  $$('[data-toggle]').forEach(b => b.onclick = () => { const t = $(`#rt${b.dataset.toggle}`); t.hidden = !t.hidden; });
}

function reportCard(r, i) {
  const t = r.totals;
  return `<div class="card report"><div class="head">
      <div><div class="title">${esc(r.title)}</div><div class="faint" style="font-size:13px">Generated ${fmtDate(r.created_at)}${r.created_by ? ' by ' + esc(r.created_by) : ''}${r.emailed_at ? ` · emailed to ${esc(r.emailed_to)}` : ''}</div></div>
      <span class="spacer"></span>
      <button class="btn sm" data-toggle="${r.id}">Details</button>
      <a class="btn sm" href="/api/reports/${r.id}/csv">${icon('download')}CSV</a>
      ${isManager() ? `<button class="btn sm" data-email="${r.id}">${icon('mail')}Email this report</button>
      <button class="btn sm danger" data-delrep="${r.id}">${icon('trash')}</button>` : ''}
    </div>
    <div class="kpis"><span><b>${t.people}</b> people</span><span><b>${hms(t.working_s)}</b> working</span><span><b>${hms(t.idle_s)}</b> non-working</span><span><b>${t.efficiency}%</b> efficiency</span>${t.pending ? `<span style="color:var(--accent)"><b style="color:inherit">${t.pending}</b> segments still unreviewed</span>` : ''}</div>
    <table class="t" id="rt${r.id}" ${i === 0 ? '' : 'hidden'}><tr><th>Person</th><th>Footage</th><th class="n">Working</th><th class="n">Non-working</th><th class="n">Efficiency</th><th class="n">Flagged</th><th class="n">Pending</th></tr>
      ${r.rows.map(x => `<tr><td>${esc(x.person)}</td><td class="muted">${esc(x.videos.join(', '))}</td><td class="n">${hms(x.working_s)}</td><td class="n">${hms(x.idle_s)}</td><td class="n">${x.efficiency}%</td><td class="n">${x.flagged}</td><td class="n">${x.pending}</td></tr>`).join('')}
    </table></div>`;
}

/* ---------- team ---------- */
async function teamPage() {
  const users = await api('/api/users');
  mount('team', `<div class="page-head"><div><h1>Team</h1><p>Managers upload footage, draw zones, review segments and send reports. Viewers can see everything but change nothing.</p></div></div>
    <div class="card" style="padding:8px 16px"><table class="t"><tr><th>Name</th><th>Email</th><th>Role</th></tr>
    ${users.map(u => `<tr><td>${esc(u.name)}</td><td>${esc(u.email)}</td><td style="width:180px"><select data-uid="${u.id}" ${u.id === ME.id ? 'disabled' : ''}>
      <option value="manager" ${u.role === 'manager' ? 'selected' : ''}>Manager</option><option value="viewer" ${u.role === 'viewer' ? 'selected' : ''}>Viewer</option></select></td></tr>`).join('')}
    </table></div><p class="faint" style="font-size:13px">New people sign up at <code>${esc(location.origin)}/#/signup</code> and join as viewers.</p>`);
  $$('[data-uid]').forEach(s => s.onchange = async () => {
    try { await api(`/api/users/${s.dataset.uid}`, { method: 'PATCH', body: { role: s.value } }); toast('Role updated'); }
    catch (e) { toast(e.message, true); route(); }
  });
}

route();
