import { $, S, t, esc, icon, api, hm, hrs, isManager, STATES, STATE_COLOR, stateLabel, pctBar, ago, fmtDay, onLeave } from '../core.js';
import { mount } from '../main.js';
import { stackedBars, donut, legendRows, spark } from '../charts.js';

export async function dashboardPage() {
  const days = +(sessionStorage.getItem('ww_days') || 14);
  const d = await api(`/api/dashboard?days=${days}`);
  const me = S.me;
  const kpi = (ic, lbl, val, foot, sp = '') => `<div class="kpi"><div class="lbl">${icon(ic)}${lbl}</div><div class="val">${val}</div><div class="foot">${foot}</div>${sp}</div>`;
  const trendW = d.trend.map(x => x.working);
  const PIPE = ['queued', 'analysing', 'annotate', 'review', 'report_ready', 'sent', 'failed'];
  const pipeMax = Math.max(1, ...PIPE.map(k => d.pipeline[k] || 0));
  const el = mount('dashboard', `<b>${t('nav.dashboard')}</b>`, `
    ${me.review_pending ? `<div class="banner">${icon('flag')}<div><b>${t('pending_banner', { n: me.review_pending })}</b> — ${t('pending_banner_sub')}</div><a class="btn sm primary" href="#/review">Open review queue</a></div>` : ''}
    ${isManager() && !me.notice_issued ? `<div class="banner info">${icon('shield')}<div><b>Issue the CCTV awareness notice.</b> DPDP requires informing workers that footage is analysed. Print it from Privacy settings and mark it issued.</div><a class="btn sm" href="#/settings/privacy">Privacy settings</a></div>` : ''}
    <div class="page-head"><div><h1>Good ${greeting()}, ${esc((me.name || '').split(' ')[0] || 'there')}</h1><p>${esc(me.org.name)} · ${fmtDay(d.range.from)} – ${fmtDay(d.range.to)} · times in IST</p></div>
      <div class="actions"><div class="seg">${[7, 14, 30].map(n => `<button data-days="${n}" class="${n === days ? 'active' : ''}">${n}d</button>`).join('')}</div>
        ${isManager() ? `<a class="btn" href="#/videos?upload=1">${icon('upload')}${t('upload_footage')}</a><a class="btn primary" href="#/reports">${icon('file')}${t('generate_report')}</a>` : ''}</div></div>
    <div class="grid g-4">
      ${kpi('clock', t('working_hours'), `${hrs(d.totals.working)}<small>h</small>`, `${hm(d.present)} observed in total`, spark(trendW))}
      ${kpi('zap', t('efficiency'), `${d.efficiency}<small>%</small>`, 'working ÷ (present − excluded)')}
      ${kpi('users', t('people_tracked'), d.people, `${d.videos} clip${d.videos === 1 ? '' : 's'} analysed`)}
      ${kpi('flag', t('pending_review'), d.pending_review, d.pending_review ? 'blocks report generation' : 'nothing blocking reports')}
    </div>
    <div class="grid g-main" style="margin-top:20px">
      <div class="card"><div class="card-head"><h2>Time by state</h2><span class="sub">per day, hours</span><span class="spacer"></span>
        <div class="legend">${STATES.map(s => `<span><span class="dot" style="background:${STATE_COLOR[s]}"></span>${esc(stateLabel(s))}</span>`).join('')}</div></div>
        <div id="trend"></div>${d.has_demo ? '<p class="faint small" style="margin:8px 0 0">The demo clip is counted on its recorded date.</p>' : ''}</div>
      <div class="card"><div class="card-head"><h2>State split</h2></div>
        <div class="donut-wrap">${donut(d.totals, { center: `${d.efficiency}%`, sub: 'efficiency' })}${legendRows(d.totals)}</div></div>
    </div>
    <div class="grid g-main" style="margin-top:20px">
      <div class="card flush"><div class="card-head" style="padding:18px 20px 0"><h2>People</h2><span class="sub">ranked by working time</span><span class="spacer"></span><a class="btn sm ghost" href="#/reports">Full report ${icon('chevron')}</a></div>
        ${d.top.length ? `<div class="table-wrap"><table class="t"><thead><tr><th>Person</th><th style="width:34%">Breakdown</th><th class="n">Working</th><th class="n">Idle</th><th class="n">Phone</th><th class="n">${t('efficiency')}</th></tr></thead><tbody>
        ${d.top.map(p => `<tr><td><div class="person-cell"><span class="avatar" style="width:28px;height:28px;font-size:11px">${esc(p.person.slice(0, 2).toUpperCase())}</span><span class="nm">${esc(p.person)}</span>${p.flagged ? `<span class="badge warn">${p.flagged}</span>` : ''}</div></td>
          <td>${pctBar(p, p.present)}</td><td class="n">${hm(p.working)}</td><td class="n">${hm(p.idle)}</td><td class="n">${hm(p.phone)}</td><td class="n"><b>${p.efficiency}%</b></td></tr>`).join('')}</tbody></table></div>`
          : `<div style="padding:20px">${noData()}</div>`}</div>
      <div class="stack">
        <div class="card"><div class="card-head"><h2>Footage pipeline</h2><span class="spacer"></span><a class="btn sm ghost" href="#/videos">${t('nav.videos')} ${icon('chevron')}</a></div>
          <div class="funnel">${PIPE.filter(k => k !== 'failed' || d.pipeline.failed).map(k => `<div class="fr"><span>${esc(t(`status.${k}`))}</span><div class="meter ${k === 'failed' ? 'hot' : ''}"><div style="width:${100 * (d.pipeline[k] || 0) / pipeMax}%"></div></div><b>${d.pipeline[k] || 0}</b></div>`).join('')}</div></div>
        <div class="card"><div class="card-head"><h2>Cameras</h2><span class="spacer"></span><a class="btn sm ghost" href="#/cameras">${icon('chevron')}</a></div>
          ${d.cameras ? `<div class="row" style="gap:18px">${[['online', 'Online'], ['offline', 'Offline'], ['rtsp', 'RTSP only'], ['not_connected', 'Not connected']].filter(([k]) => d.camera_health[k]).map(([k, l]) => `<span class="health ${k}">${d.camera_health[k]} ${l}</span>`).join('')}</div>`
            : `<p class="muted small" style="margin:0">No cameras yet. ${isManager() ? '<a href="#/cameras" style="color:var(--accent)">Add a camera</a> to receive shift slices automatically.' : ''}</p>`}</div>
      </div>
    </div>
    <div class="grid g-2" style="margin-top:20px">
      <div class="card"><div class="card-head"><h2>Zones</h2><span class="sub">where time was spent</span></div>
        ${d.zones.length ? `<table class="t"><tbody>${d.zones.slice(0, 8).map(z => { const tot = STATES.reduce((a, s) => a + z[s], 0); return `<tr><td>${esc(z.zone)}</td><td style="width:45%">${pctBar(z, tot)}</td><td class="n">${hm(tot)}</td></tr>`; }).join('')}</tbody></table>` : noData()}</div>
      <div class="card"><div class="card-head"><h2>Activity</h2></div>
        ${d.recent.length ? `<div class="feed">${d.recent.map(n => `<a href="#${esc(n.link || '/dashboard')}"><span class="ic">${icon(EVT[n.event] || 'bell')}</span><div><div class="t">${esc(n.title)}</div><div class="s">${ago(n.created_at)}</div></div></a>`).join('')}</div>` : '<p class="muted small" style="margin:0">Nothing yet.</p>'}</div>
    </div>`);
  const draw = () => stackedBars($('#trend', el), d.trend);
  draw();
  const ro = new ResizeObserver(draw); ro.observe($('#trend', el)); onLeave(() => ro.disconnect());
  el.querySelectorAll('[data-days]').forEach(b => b.onclick = () => { sessionStorage.setItem('ww_days', b.dataset.days); dashboardPage(); });
}

const EVT = { slice_ready: 'video', analysis_failed: 'alert', review_pending: 'flag', report_ready: 'file', camera_offline: 'cctv', quota_near: 'gpu', payment_failed: 'card' };
const greeting = () => { const h = +new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', hour: 'numeric', hour12: false }).format(new Date()); return h < 12 ? 'morning' : h < 17 ? 'afternoon' : 'evening'; };
const noData = () => `<p class="muted small" style="margin:0">No analysed footage in this period yet. ${isManager() ? '<a href="#/videos?upload=1" style="color:var(--accent)">Upload footage</a>' : ''}</p>`;
