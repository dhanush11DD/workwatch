/* WorkWatch — app shell, router, landing and sign-in. Plain ES modules, no build step. */
import { $, $$, S, t, esc, icon, api, toast, fail, isManager, initials, ago, STATES, STATE_COLOR, stateLabel } from './core.js';
import { dashboardPage } from './pages/dashboard.js';
import { videosPage, videoPage, jobsPage } from './pages/videos.js';
import { reviewPage } from './pages/review.js';
import { reportsPage } from './pages/reports.js';
import { workersPage, camerasPage } from './pages/org.js';
import { settingsPage } from './pages/settings.js';

const app = $('#app');

/* ---------- shell ---------- */
const NAV = [
  ['nav.overview', [['dashboard', 'dashboard', 'nav.dashboard']]],
  ['nav.footage', [['videos', 'video', 'nav.videos'], ['cameras', 'cctv', 'nav.cameras'], ['jobs', 'gpu', 'nav.jobs']]],
  ['nav.review', [['review', 'review', 'nav.review'], ['reports', 'file', 'nav.reports']]],
  ['nav.org', [['workers', 'users', 'nav.workers'], ['settings', 'settings', 'nav.settings']]],
];

export function mount(active, crumbs, inner) {
  const me = S.me, org = me.org;
  const trialDays = org.plan === 'trial' && org.trial_ends ? Math.max(0, Math.ceil((org.trial_ends - Date.now() / 1000) / 86400)) : null;
  app.innerHTML = `<div class="layout">
    <aside class="sidebar">
      <a class="brand" href="#/dashboard">${icon('cctv')}<span>WorkWatch<span class="org">${esc(org.name)}</span></span></a>
      <nav class="side-nav">${NAV.map(([g, items]) => `<div class="group">${t(g)}</div>` + items.map(([h, ic, l]) =>
        `<a href="#/${h}" class="${active === h ? 'active' : ''}">${icon(ic)}<span>${t(l)}</span>${h === 'review' && me.review_pending ? `<span class="count">${me.review_pending}</span>` : ''}</a>`).join('')).join('')}</nav>
      <div class="side-foot"><div class="plan-card">${trialDays != null ? `<b>${t('trial_left', { n: trialDays })}</b><div class="meter"><div style="width:${100 - (trialDays / 14) * 100}%"></div></div>
        ${isManager() ? '<a href="#/settings/billing" class="small" style="display:inline-block;margin-top:8px;color:var(--accent);text-decoration:none">Choose a plan →</a>' : ''}`
        : `<b style="text-transform:capitalize">${esc(org.plan)}</b> plan`}</div></div>
    </aside>
    <div class="scrim"></div>
    <div class="main">
      <header class="topbar">
        <button class="icon-btn menu-btn" id="menu" aria-label="Menu">${icon('menu')}</button>
        <div class="crumbs">${crumbs}</div>
        <div class="right">
          <button class="icon-btn" id="bell" aria-label="${t('notifications')}">${icon('bell')}<span class="pip" hidden></span></button>
          <button class="user-btn" id="user"><span class="avatar">${esc(initials(me.name || me.email))}</span><span class="who">${esc(me.name || me.email || me.phone)}<span>${t(me.role)}</span></span></button>
        </div>
      </header>
      <main class="content">${inner}</main>
    </div></div>`;
  $('#menu').onclick = () => $('.layout').classList.toggle('nav-open');
  $('.scrim').onclick = () => $('.layout').classList.remove('nav-open');
  $('#bell').onclick = e => { e.stopPropagation(); notifPanel(); };
  $('#user').onclick = e => { e.stopPropagation(); userMenu(); };
  refreshBell();
  return $('.content');
}

function closeDropdowns() { $$('.dropdown').forEach(d => d.remove()); }
document.addEventListener('click', e => { if (!e.target.closest('.dropdown')) closeDropdowns(); });

async function refreshBell() {
  try {
    const n = await api('/api/notifications');
    const pip = $('#bell .pip');
    if (pip) { pip.hidden = !n.unread; pip.textContent = n.unread > 9 ? '9+' : n.unread; }
    return n;
  } catch { return { items: [], unread: 0 }; }
}
setInterval(() => { if (S.me && document.visibilityState === 'visible') refreshBell(); }, 30000);

async function notifPanel() {
  if ($('.dropdown.notif')) return closeDropdowns();
  closeDropdowns();
  const n = await refreshBell();
  const d = document.createElement('div');
  d.className = 'dropdown notif';
  d.innerHTML = `<div class="dh">${t('notifications')}<button class="btn xs ghost" id="readall">${t('mark_all_read')}</button></div>
    <div class="list">${n.items.length ? n.items.map(x => `<a class="item ${x.read ? '' : 'unread'}" href="#${esc(x.link || '/dashboard')}" data-id="${x.id}">
      <div><div class="t">${esc(x.title)}</div><div class="s">${esc(x.body || '')}</div><div class="s">${ago(x.created_at)}</div></div></a>`).join('')
      : `<div class="item"><div class="s">${t('no_notifications')}</div></div>`}</div>`;
  document.body.appendChild(d);
  $('#readall', d).onclick = async () => { await api('/api/notifications/read', { method: 'POST', body: {} }); closeDropdowns(); refreshBell(); };
  $$('[data-id]', d).forEach(a => a.addEventListener('click', () => api('/api/notifications/read', { method: 'POST', body: { ids: [+a.dataset.id] } }).then(refreshBell)));
}

function userMenu() {
  if ($('.dropdown.um')) return closeDropdowns();
  closeDropdowns();
  const d = document.createElement('div');
  d.className = 'dropdown sm um';
  d.innerHTML = `<div class="dh" style="display:block"><div>${esc(S.me.name || '')}</div><div class="small muted" style="font-weight:400">${esc(S.me.email || S.me.phone || '')}</div></div>
    <a class="mi" href="#/settings/profile">${icon('user')}${t('profile')}</a>
    <button class="mi" id="lang">${icon('globe')}${t('language')}: ${S.lang === 'hi' ? 'हिन्दी' : 'English'}</button>
    <button class="mi" id="out">${icon('logout')}${t('sign_out')}</button>`;
  document.body.appendChild(d);
  $('#lang', d).onclick = async () => {
    S.lang = S.lang === 'hi' ? 'en' : 'hi';
    localStorage.setItem('ww_lang', S.lang);
    document.documentElement.lang = S.lang;
    api('/api/auth/profile', { method: 'PATCH', body: { language: S.lang } }).catch(() => { });
    closeDropdowns(); route();
  };
  $('#out', d).onclick = async () => { await api('/api/auth/logout', { method: 'POST' }); S.me = null; location.hash = '#/'; };
}

export async function refreshMe() { S.me = await api('/api/auth/me'); return S.me; }

/* ---------- router ---------- */
export async function route() {
  S.cleanup.forEach(f => { try { f(); } catch { } });
  S.cleanup = [];
  $$('.modal').forEach(m => m.remove());
  closeDropdowns();
  const [path] = location.hash.replace(/^#/, '').split('?');
  const [, page = '', id] = path.split('/');
  if (page === '') return landing();
  if (page === 'login' || page === 'signup') return authPage(page);
  if (page === 'invite') return invitePage(id);
  if (!S.me) {
    try { await refreshMe(); } catch { location.hash = '#/login'; return; }
    if (S.me.language && !localStorage.getItem('ww_lang')) S.lang = S.me.language;
  } else refreshMe().catch(() => { });
  document.documentElement.lang = S.lang;
  window.scrollTo(0, 0);
  try {
    if (page === 'dashboard') return await dashboardPage();
    if (page === 'videos' && id) return await videoPage(+id);
    if (page === 'videos') return await videosPage();
    if (page === 'jobs') return await jobsPage();
    if (page === 'review') return await reviewPage();
    if (page === 'reports') return await reportsPage();
    if (page === 'workers') return await workersPage();
    if (page === 'cameras') return await camerasPage();
    if (page === 'settings') return await settingsPage(id || 'profile');
    if (page === 'demo') {
      const vids = await api('/api/videos');
      const demo = vids.find(v => v.is_demo) || vids[0];
      return location.replace(demo ? `#/videos/${demo.id}` : '#/videos');
    }
    location.hash = '#/dashboard';
  } catch (e) { if (e.status !== 401) { fail(e); console.error(e); } }
}
window.addEventListener('hashchange', route);
window.addEventListener('ww:route', route);

/* ---------- landing ---------- */
function landing() {
  const f = (i, h, p) => `<div class="feature">${icon(i)}<h3>${h}</h3><p>${p}</p></div>`;
  const bar = parts => `<div class="track">${parts.map(([s, w]) => `<div style="width:${w}%;background:${STATE_COLOR[s]}"></div>`).join('')}</div>`;
  app.innerHTML = `<header class="land-top"><a class="brand" href="#/">${icon('cctv')}WorkWatch</a>
    <div class="right"><a class="btn ghost" href="#/login">${t('sign_in')}</a><a class="btn primary" href="#/signup">Start free trial</a></div></header>
  <main class="land">
    <section class="hero"><div>
      <div class="eyebrow">${icon('zap')}Video analytics for Indian shop floors</div>
      <h1>Know where every <em>working hour</em> goes — straight from your CCTV.</h1>
      <p>WorkWatch tracks each worker in your footage, separates working, idle, phone, break and excluded time using the zones you draw, and sends a manager-approved report to WhatsApp and email every day.</p>
      <div class="row" style="gap:12px"><a class="btn primary lg" href="#/signup">Start 14-day trial</a><a class="btn lg" href="#/login">${t('sign_in')}</a></div>
      <p class="faint small" style="margin-top:18px">DPDP-ready: awareness notices, face blur, 30/60/90-day retention, audit trail. Data stays in India.</p>
    </div>
    <div class="hero-art"><div class="row"><b>Shift A · Fabrication bay</b><span class="spacer"></span><span class="badge ok"><span class="d"></span>Report ready</span></div>
      <div class="bars">${[['Ravi K.', [['working', 72], ['idle', 8], ['phone', 6], ['break', 14]]], ['Asha M.', [['working', 81], ['idle', 5], ['break', 14]]],
        ['Imran S.', [['working', 55], ['idle', 19], ['phone', 12], ['break', 10], ['exclusion', 4]]], ['Deepa R.', [['working', 77], ['phone', 3], ['break', 13], ['idle', 7]]]]
        .map(([n, p]) => `<div class="hb"><span>${n}</span>${bar(p)}</div>`).join('')}</div>
      <div class="states-legend" style="margin-top:16px">${STATES.map(s => `<span><span class="dot" style="background:${STATE_COLOR[s]}"></span>${esc(stateLabel(s))}</span>`).join('')}</div></div>
    </section>
    <section class="features">
      ${f('upload', 'Upload or connect CCTV', 'Resumable uploads for multi-GB recordings, or an edge agent that slices RTSP streams by shift and uploads them automatically.')}
      ${f('users', 'Name people once', 'Pick who is who on a reference frame, remove visitors, merge split tracks. Names come from your saved worker list.')}
      ${f('map', 'Draw zones on the frame', 'Work, break and exclusion zones per camera, saved as templates so every new shift is ready to go.')}
      ${f('gpu', 'YOLOv8 + pose on GPU', 'Person and phone detection, ByteTrack tracking and pose-assisted phone-call detection on a cloud GPU queue.')}
      ${f('review', 'Review before it counts', 'Low-confidence and short segments are flagged. Reports stay blocked until a reviewer approves or reclassifies them.')}
      ${f('sheet', 'Payroll-ready reports', 'Excel, PDF and CSV plus greytHR, Keka, Zoho Payroll and Tally formats — delivered on WhatsApp and email.')}
    </section>
  </main>`;
}

/* ---------- sign in / sign up ---------- */
async function authPage(mode, invite = null) {
  const signup = mode === 'signup';
  const cfg = await api('/api/auth/config').catch(() => ({}));
  const err = new URLSearchParams(location.hash.split('?')[1] || '').get('error');
  app.innerHTML = `<div class="auth">
    <div class="side"><a class="brand" href="#/">${icon('cctv')}WorkWatch</a>
      <blockquote>“We stopped guessing at overtime. The daily WhatsApp report tells us exactly who was on the line and for how long.”<span>Built for factories, warehouses, kitchens and retail floors.</span></blockquote></div>
    <div class="form-side"><div class="box">
      <h2>${invite ? `Join ${esc(invite.org)}` : signup ? 'Create your workspace' : 'Welcome back'}</h2>
      <p class="sub">${invite ? `You were invited as a <b>${esc(invite.role)}</b> (${esc(invite.email)}).` : signup ? '14-day free trial. No card needed.' : 'Sign in to your WorkWatch workspace.'}</p>
      ${err ? '<div class="banner err">Google sign-in failed. Try again or use another method.</div>' : ''}
      ${cfg.google ? `<a class="btn block" href="/api/auth/google/start${invite ? `?invite=${encodeURIComponent(invite.token)}` : ''}">${googleG()}Continue with Google</a><div class="or">or</div>` : ''}
      <div class="seg" style="width:100%;margin-bottom:18px"><button class="active" data-m="email" style="flex:1">Email</button><button data-m="otp" style="flex:1">Mobile OTP</button></div>
      <form id="f-email">
        ${signup && !invite ? '<div class="field"><label>Company name</label><input type="text" name="company" required placeholder="Acme Steel Pvt Ltd"></div>' : ''}
        ${signup || invite ? '<div class="field"><label>Your name</label><input type="text" name="name" required placeholder="Priya Sharma" autocomplete="name"></div>' : ''}
        ${invite ? '' : '<div class="field"><label>Work email</label><input type="email" name="email" placeholder="you@company.com" required autocomplete="email"></div>'}
        <div class="field"><label>Password</label><input type="password" name="password" placeholder="••••••••" required minlength="${signup || invite ? 8 : 1}" autocomplete="${signup || invite ? 'new-password' : 'current-password'}"></div>
        <div class="error" hidden></div>
        <button class="btn primary block lg">${invite ? 'Accept invite' : signup ? t('sign_up') : t('sign_in')}</button>
      </form>
      <form id="f-otp" hidden>
        ${signup && !invite ? '<div class="field"><label>Company name</label><input type="text" name="company" placeholder="Acme Steel Pvt Ltd"></div>' : ''}
        ${signup || invite ? '<div class="field"><label>Your name</label><input type="text" name="name" placeholder="Priya Sharma"></div>' : ''}
        <div class="field"><label>Mobile number</label><input type="tel" name="phone" placeholder="98765 43210" required autocomplete="tel"><span class="hint">Indian numbers get +91 automatically.</span></div>
        <div class="field" id="code-f" hidden><label>6-digit code</label><input type="text" name="code" inputmode="numeric" maxlength="6" autocomplete="one-time-code"></div>
        <div class="otp-dev" hidden></div><div class="error" hidden></div>
        <button class="btn primary block lg" id="otp-btn">Send code</button>
      </form>
      ${invite ? '' : `<div class="switch-link">${signup ? 'Already have a workspace? <a href="#/login">Sign in</a>' : 'New to WorkWatch? <a href="#/signup">Create a workspace</a>'}</div>`}
    </div></div></div>`;
  $$('.seg button').forEach(b => b.onclick = () => {
    $$('.seg button').forEach(x => x.classList.toggle('active', x === b));
    $('#f-email').hidden = b.dataset.m !== 'email'; $('#f-otp').hidden = b.dataset.m !== 'otp';
  });
  const done = async () => { await refreshMe(); location.hash = '#/dashboard'; };
  const showErr = (f, e) => { const el = $('.error', f); el.hidden = false; el.textContent = e.message; };
  $('#f-email').onsubmit = async e => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    try {
      if (invite) await api(`/api/auth/invite/${invite.token}/accept`, { method: 'POST', body });
      else await api(`/api/auth/${signup ? 'signup' : 'login'}`, { method: 'POST', body });
      await done();
    } catch (er) { showErr(e.target, er); }
  };
  let sent = false;
  $('#f-otp').onsubmit = async e => {
    e.preventDefault();
    const f = e.target, body = Object.fromEntries(new FormData(f));
    try {
      if (!sent) {
        const r = await api('/api/auth/otp/send', { method: 'POST', body: { phone: body.phone } });
        sent = true; $('#code-f').hidden = false; $('#otp-btn').textContent = 'Verify & continue';
        if (r.dev) { const d = $('.otp-dev'); d.hidden = false; d.textContent = 'SMS is not configured on this server — the code was written to the server log.'; }
        $('[name=code]', f).focus();
      } else {
        await api('/api/auth/otp/verify', { method: 'POST', body: { ...body, invite: invite?.token } });
        await done();
      }
    } catch (er) { showErr(f, er); }
  };
}
const googleG = () => '<svg width="16" height="16" viewBox="0 0 48 48"><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.6 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"/><path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"/></svg>';

async function invitePage(token) {
  try {
    const inv = await api(`/api/auth/invite/${token}`);
    await authPage('signup', { ...inv, token });
  } catch (e) {
    app.innerHTML = `<div class="auth" style="grid-template-columns:1fr"><div class="form-side"><div class="box"><h2>Invite unavailable</h2><p class="sub">${esc(e.message)}</p><a class="btn primary" href="#/login">${t('sign_in')}</a></div></div></div>`;
  }
}

route();
