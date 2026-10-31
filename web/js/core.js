/* Shared helpers: DOM, formatting (IST), API, i18n, icons, modals, toasts. */
import { DICT } from './i18n.js';

export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export const S = { me: null, lang: localStorage.getItem('ww_lang') || 'en', cleanup: [] };
export const onLeave = fn => S.cleanup.push(fn);
export const isManager = () => S.me?.role === 'manager';
export const canReview = () => !!S.me?.can_review;

/* ---------- i18n (en / hi) ---------- */
export const t = (k, vars) => {
  let s = (DICT[S.lang] && DICT[S.lang][k]) || DICT.en[k] || k;
  if (vars) for (const [a, b] of Object.entries(vars)) s = s.replace(`{${a}}`, b);
  return s;
};

/* ---------- five states ---------- */
export const STATES = ['working', 'idle', 'phone', 'break', 'exclusion'];
export const STATE_COLOR = { working: '#eeb23e', idle: '#64748b', phone: '#a78bfa', break: '#5b8def', exclusion: '#e5534b' };
export const stateLabel = s => S.me?.labels?.[s] && S.lang === 'en' ? S.me.labels[s] : t(`state.${s}`);
export const stateChip = s => `<span class="state-chip"><i style="background:${STATE_COLOR[s]}"></i>${esc(stateLabel(s))}</span>`;
export const ZONE_COLORS = { work: '#eeb23e', break: '#5b8def', exclusion: '#e5534b' };
export const zoneLabel = z => t(`zone.${z}`);

/* ---------- formatting ---------- */
const tz = () => S.me?.org?.timezone || 'Asia/Kolkata';
const loc = () => (S.lang === 'hi' ? 'hi-IN' : 'en-IN');
export const hms = s => { s = Math.round(s || 0); return `${Math.floor(s / 3600)}:${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; };
export const hm = s => { s = Math.round(s || 0); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return h ? `${h}h ${String(m).padStart(2, '0')}m` : m ? `${m}m ${String(s % 60).padStart(2, '0')}s` : `${s % 60}s`; };
export const clock = x => { x = Math.max(0, Math.floor(x || 0)); const h = Math.floor(x / 3600), m = Math.floor(x % 3600 / 60), s = String(x % 60).padStart(2, '0'); return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`; };
export const hrs = s => ((s || 0) / 3600).toFixed(s >= 36000 ? 0 : s >= 3600 ? 1 : 2);
export const fmtTs = ts => ts ? new Intl.DateTimeFormat(loc(), { timeZone: tz(), day: '2-digit', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(ts * 1000)) : '—';
export const fmtDay = iso => { if (!iso) return '—'; const [y, m, d] = iso.split('-').map(Number); return new Intl.DateTimeFormat(loc(), { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(Date.UTC(y, m - 1, d)); };
export const ago = ts => { if (!ts) return t('never'); const d = Date.now() / 1000 - ts; if (d < 60) return t('just_now'); if (d < 3600) return t('min_ago', { n: Math.floor(d / 60) }); if (d < 86400) return t('h_ago', { n: Math.floor(d / 3600) }); return fmtTs(ts); };
export const inr = n => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n || 0);
export const todayIST = () => new Intl.DateTimeFormat('en-CA', { timeZone: tz() }).format(new Date());
export const initials = n => (n || '?').split(/\s+/).map(x => x[0]).join('').slice(0, 2).toUpperCase();

/* ---------- api ---------- */
export class ApiError extends Error { constructor(msg, status, detail) { super(msg); this.status = status; this.detail = detail; } }
export async function api(path, opts = {}) {
  const o = { credentials: 'same-origin', ...opts };
  if (o.body && !(o.body instanceof FormData)) { o.body = JSON.stringify(o.body); o.headers = { 'Content-Type': 'application/json', ...(o.headers || {}) }; }
  const r = await fetch(path, o);
  if (r.status === 401 && !path.startsWith('/api/auth')) { S.me = null; location.hash = '#/login'; throw new ApiError(t('sign_in_required'), 401); }
  const data = r.headers.get('content-type')?.includes('json') ? await r.json() : await r.text();
  if (!r.ok) {
    const d = data?.detail;
    throw new ApiError(typeof d === 'string' ? d : d?.message || (Array.isArray(d) ? d.map(x => x.msg).join('; ') : r.statusText), r.status, d);
  }
  return data;
}
export const download = (url) => { const a = document.createElement('a'); a.href = url; a.download = ''; document.body.appendChild(a); a.click(); a.remove(); };

/* ---------- icons (lucide, MIT) ---------- */
const I = {
  cctv: '<path d="M16.75 12h3.632a1 1 0 0 1 .894 1.447l-2.034 4.069a1 1 0 0 1-1.708.134l-2.124-2.97"/><path d="M17.106 9.053a1 1 0 0 1 .447 1.341l-3.106 6.211a1 1 0 0 1-1.342.447L3.61 12.3a2.92 2.92 0 0 1-1.3-3.91L3.69 5.6a2.92 2.92 0 0 1 3.92-1.3z"/><path d="M2 19h3.76a2 2 0 0 0 1.8-1.1L9 15"/><path d="M2 21v-4"/><path d="M7 9h.01"/>',
  dashboard: '<rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
  map: '<path d="M14.106 5.553a2 2 0 0 0 1.788 0l3.659-1.83A1 1 0 0 1 21 4.619v12.764a1 1 0 0 1-.553.894l-4.553 2.277a2 2 0 0 1-1.788 0l-4.212-2.106a2 2 0 0 0-1.788 0l-3.659 1.83A1 1 0 0 1 3 19.381V6.618a1 1 0 0 1 .553-.894l4.553-2.277a2 2 0 0 1 1.788 0z"/><path d="M15 5.764v15"/><path d="M9 3.236v15"/>',
  review: '<rect width="8" height="4" x="8" y="2" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="m9 14 2 2 4-4"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  user: '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  flag: '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" x2="4" y1="22" y2="15"/>',
  video: '<path d="m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.87a.5.5 0 0 0-.752-.432L16 10.5"/><rect x="2" y="6" width="14" height="12" rx="2"/>',
  logout: '<path d="m10 17-5-5 5-5"/><path d="M5 12h12"/><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/>',
  mail: '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  pencil: '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/>',
  trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
  plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  camera: '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/>',
  merge: '<path d="m8 6 4-4 4 4"/><path d="M12 2v10.3a4 4 0 0 1-1.172 2.872L4 22"/><path d="m20 22-5-5"/>',
  file: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>',
  sheet: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M8 13h2"/><path d="M14 13h2"/><path d="M8 17h2"/><path d="M14 17h2"/>',
  refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
  bell: '<path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326"/>',
  settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
  menu: '<line x1="4" x2="20" y1="12" y2="12"/><line x1="4" x2="20" y1="6" y2="6"/><line x1="4" x2="20" y1="18" y2="18"/>',
  building: '<rect width="16" height="20" x="4" y="2" rx="2" ry="2"/><path d="M9 22v-4h6v4"/><path d="M8 6h.01"/><path d="M16 6h.01"/><path d="M12 6h.01"/><path d="M12 10h.01"/><path d="M12 14h.01"/><path d="M16 10h.01"/><path d="M16 14h.01"/><path d="M8 10h.01"/><path d="M8 14h.01"/>',
  shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
  history: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
  card: '<rect width="20" height="14" x="2" y="5" rx="2"/><line x1="2" x2="22" y1="10" y2="10"/>',
  plug: '<path d="M12 22v-5"/><path d="M9 8V2"/><path d="M15 8V2"/><path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z"/>',
  alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  sliders: '<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/>',
  send: '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/><path d="m21.854 2.147-10.94 10.939"/>',
  whatsapp: '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>',
  phone: '<rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/>',
  layers: '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
  eye: '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
  eyeoff: '<path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49"/><path d="M14.084 14.158a3 3 0 0 1-4.242-4.242"/><path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143"/><path d="m2 2 20 20"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  copy: '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  gpu: '<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/>',
  globe: '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
  chevron: '<path d="m9 18 6-6-6-6"/>',
  back: '<path d="m15 18-6-6 6-6"/>',
  box: '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
  zap: '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
  printer: '<path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><path d="M6 9V3a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v6"/><rect x="6" y="14" width="12" height="8" rx="1"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  note: '<path d="M12 20h9"/><path d="M16.376 3.622a1 1 0 0 1 3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506l-2.872.838a.5.5 0 0 1-.62-.62l.838-2.872a2 2 0 0 1 .506-.854z"/>',
  key: '<path d="m15.5 7.5 2.3 2.3a1 1 0 0 0 1.4 0l2.1-2.1a1 1 0 0 0 0-1.4L19 4"/><path d="m21 2-9.6 9.6"/><circle cx="7.5" cy="15.5" r="5.5"/>',
  lock: '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
};
export const icon = (n, cls = '') => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${I[n] || ''}</svg>`;

/* ---------- toasts + modals ---------- */
export function toast(msg, err = false) {
  let box = $('.toasts');
  if (!box) { box = document.createElement('div'); box.className = 'toasts'; document.body.appendChild(box); }
  const el = document.createElement('div');
  el.className = 'toast' + (err ? ' err' : '');
  el.innerHTML = `${icon(err ? 'alert' : 'check')}<div>${esc(msg)}</div>`;
  box.appendChild(el);
  setTimeout(() => el.remove(), err ? 7000 : 3500);
}
export const fail = e => toast(e.message || String(e), true);

export function modal(html, { size = '' } = {}) {
  const m = document.createElement('div');
  m.className = 'modal';
  m.innerHTML = `<div class="card ${size}" role="dialog" aria-modal="true">${html}</div>`;
  const close = () => { if (!m.isConnected) return; m.remove(); document.removeEventListener('keydown', key); m.dispatchEvent(new Event('closed')); };
  const key = e => { if (e.key === 'Escape' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) close(); };
  m.addEventListener('mousedown', e => { if (e.target === m) close(); });
  document.addEventListener('keydown', key);
  $$('[data-close]', m).forEach(b => b.onclick = close);
  document.body.appendChild(m);
  m.close = close;
  return m;
}

export function formModal(title, fieldsHtml, submit, { label = t('save'), sub = '', size = 'narrow' } = {}) {
  const m = modal(`<h3>${esc(title)}</h3>${sub ? `<p class="muted small" style="margin:0 0 14px">${sub}</p>` : '<div style="height:10px"></div>'}<form>${fieldsHtml}<div class="error" hidden></div>
    <div class="mfoot"><button type="button" class="btn" data-close>${t('cancel')}</button><button class="btn primary">${esc(label)}</button></div></form>`, { size });
  $('form', m).onsubmit = async e => {
    e.preventDefault();
    const btn = $('button.primary', m); btn.disabled = true;
    try { await submit(new FormData(e.target), m); m.close(); }
    catch (err) { const el = $('.error', m); el.hidden = false; el.textContent = err.message; btn.disabled = false; }
  };
  setTimeout(() => $('input:not([type=hidden]),select,textarea', m)?.focus(), 30);
  return m;
}

export function confirmBox(title, body, { label = t('confirm'), danger = false, typed = null } = {}) {
  return new Promise(res => {
    const m = modal(`<h3>${esc(title)}</h3><p class="muted" style="margin:6px 0 14px">${body}</p>
      ${typed ? `<div class="field"><label>${t('type_to_confirm', { x: esc(typed) })}</label><input type="text" id="typed" autocomplete="off"></div>` : ''}
      <div class="mfoot"><button class="btn" data-close>${t('cancel')}</button><button class="btn ${danger ? 'danger solid' : 'primary'}" id="ok" ${typed ? 'disabled' : ''}>${esc(label)}</button></div>`, { size: 'narrow' });
    let done = false;
    if (typed) $('#typed', m).oninput = e => { $('#ok', m).disabled = e.target.value !== typed; };
    $('#ok', m).onclick = () => { done = true; res(typed ? $('#typed', m).value : true); m.close(); };
    m.addEventListener('closed', () => { if (!done) res(false); });
  });
}

/* ---------- small UI bits ---------- */
export const field = (label, input, hint = '') => `<div class="field"><label>${label}</label>${input}${hint ? `<span class="hint">${hint}</span>` : ''}</div>`;
export const opt = (v, l, sel) => `<option value="${esc(v)}" ${String(v) === String(sel ?? '') ? 'selected' : ''}>${esc(l)}</option>`;
export const empty = (ic, msg) => `<div class="empty">${icon(ic)}<div>${msg}</div></div>`;
export const pctBar = (parts, total) => `<div class="bar">${STATES.map(s => parts[s] ? `<div style="width:${100 * parts[s] / (total || 1)}%;background:${STATE_COLOR[s]}"></div>` : '').join('')}</div>`;
export const statusBadge = v => {
  const cls = { queued: 'warn', analysing: 'warn', failed: 'err', uploaded: 'flat', slice: 'flat', annotate: 'info', review: 'warn', report_ready: 'ok', sent: 'ok' }[v.status] || 'flat';
  const pct = v.status === 'analysing' && v.job ? ` ${Math.round(v.job.progress * 100)}%` : '';
  return `<span class="badge ${cls}"><span class="d"></span>${esc(t(`status.${v.status}`))}${pct}</span>`;
};
export function copyText(s) { navigator.clipboard?.writeText(s).then(() => toast(t('copied'))); }
