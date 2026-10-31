import { $, $$, S, t, esc, icon, api, toast, fail, modal, formModal, canReview, clock, fmtDay, fmtTs, STATES, STATE_COLOR, stateLabel, stateChip, opt, empty, field } from '../core.js';
import { mount, refreshMe } from '../main.js';

export async function reviewPage() {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  const status = params.get('status') || 'pending', video = params.get('video') || '', state = params.get('state') || '';
  const q = new URLSearchParams({ status, ...(video && { video_id: video }), ...(state && { state }) });
  const [data, all] = await Promise.all([api(`/api/review?${q}`), api('/api/review?status=pending')]);
  const items = data.items;
  const can = canReview();
  const videos = [...new Map(all.items.map(s => [s.video_id, s.video_name])).entries()];
  const setQ = (k, val) => { const p = new URLSearchParams(location.hash.split('?')[1] || ''); val ? p.set(k, val) : p.delete(k); location.hash = `#/review?${p}`; };
  const el = mount('review', `<b>${t('nav.review')}</b>`, `
    ${all.items.length ? `<div class="banner">${icon('flag')}<div><b>${t('pending_banner', { n: all.items.length })}</b> — ${t('pending_banner_sub')}</div></div>`
      : `<div class="banner ok">${icon('check')}<div><b>Review queue is clear.</b> Reports can be generated for every annotated clip.</div><a class="btn sm" href="#/reports">${t('nav.reports')}</a></div>`}
    <div class="page-head"><div><h1>${t('nav.review')}</h1><p>Segments the pipeline is unsure about. Approve them, or reclassify to the right state. Every decision is saved to the audit trail.</p></div></div>
    <div class="tabs">${[['pending', 'Pending', all.items.length], ['awaiting_annotation', 'Awaiting annotation', data.awaiting_annotation], ['done', 'Reviewed', null]]
      .map(([k, l, n]) => `<a href="#/review?status=${k}" class="${status === k ? 'active' : ''}">${l}${n != null ? `<span class="count">${n}</span>` : ''}</a>`).join('')}</div>
    <div class="filters" style="margin-bottom:16px">
      ${field('Footage', `<select id="fv"><option value="">All footage</option>${videos.map(([id, n]) => opt(id, n, video)).join('')}</select>`)}
      ${field('Detected state', `<select id="fs"><option value="">Any state</option>${STATES.map(s => opt(s, stateLabel(s), state)).join('')}</select>`)}
    </div>
    <div class="card flush">
      ${status === 'pending' && items.length && can ? `<div class="bulkbar"><label class="check" style="margin:0"><input type="checkbox" id="all"> Select all</label><span class="muted small" id="selcount">0 selected</span><span class="spacer"></span>
        <label class="check small" style="margin:0" title="Also include every pending item with the same flag reason and detected state on the same footage"><input type="checkbox" id="similar"> Include similar</label>
        <button class="btn sm" id="bulk-approve" disabled>${icon('check')}${t('approve')}</button>
        <select class="sm" id="bulk-state" style="width:auto" disabled><option value="">${t('reclassify')} as…</option>${STATES.map(s => opt(s, stateLabel(s))).join('')}</select></div>` : ''}
      ${status === 'awaiting_annotation' && items.length ? `<div class="banner info" style="margin:16px">${icon('info')}<div>These clips still need people & zones confirmed. Flagged items move into the queue once annotation is finished.</div></div>` : ''}
      <div class="rv-list">${items.length ? items.map(s => item(s, status, can)).join('') : `<div style="padding:20px">${empty('review', status === 'pending' ? 'Nothing waiting for review.' : 'No items here.')}</div>`}</div>
    </div>`);
  $('#fv', el).onchange = e => setQ('video', e.target.value);
  $('#fs', el).onchange = e => setQ('state', e.target.value);
  wire(el, items);
}

function item(s, status, can) {
  const changed = s.review_status === 'reclassified';
  return `<div class="rv" data-id="${s.id}">
    ${status === 'pending' && can ? `<input type="checkbox" data-sel="${s.id}" aria-label="Select">` : '<span></span>'}
    ${s.thumb ? `<img src="/api/runs/${s.run_id}/thumbs/${esc(s.thumb)}" alt="">` : '<div class="ph"></div>'}
    <div style="min-width:0"><div class="title">${esc(s.person)}</div>
      <div class="sub"><a href="#/videos/${s.video_id}" style="text-decoration:none">${esc(s.video_name)}</a> · ${fmtDay(s.recorded_on)} · ${clock(s.start)}–${clock(s.end)} (${Math.round(s.end - s.start)}s)${s.zone ? ` · ${esc(s.zone)}` : ''}</div>
      ${s.flag_reason ? `<div class="reason">${icon('flag', 'ic12')} ${esc(s.flag_reason)}</div>` : ''}${s.note ? `<div class="note">“${esc(s.note)}”</div>` : ''}</div>
    <div class="meta2"><div class="row" style="gap:6px">${changed ? `<span style="text-decoration:line-through;opacity:.6">${stateChip(s.state)}</span>${icon('chevron', 'ic12')}` : ''}${stateChip(s.effective_state)}</div>
      <div class="small faint" style="margin-top:4px">confidence ${Math.round((s.confidence || 0) * 100)}%${s.reviewed_by ? ` · ${esc(s.reviewed_by)} ${fmtTs(s.reviewed_at)}` : ''}</div></div>
    <div class="acts"><button class="btn sm ghost" data-play="${s.id}" title="Watch the clip">${icon('play')}</button>
      ${can ? (status === 'done' ? `<button class="btn sm ghost" data-hist="${s.id}" title="History">${icon('history')}</button><button class="btn sm" data-reopen="${s.id}">Reopen</button>`
        : `<button class="btn sm ghost" data-note="${s.id}" title="${t('note')}">${icon('note')}</button>
        <select data-re="${s.id}" aria-label="${t('reclassify')}"><option value="">${t('reclassify')}…</option>${STATES.map(x => opt(x, stateLabel(x))).join('')}</select>
        <button class="btn sm primary" data-ok="${s.id}">${icon('check')}${t('approve')}</button>`) : ''}</div></div>`;
}

function wire(el, items) {
  const byId = Object.fromEntries(items.map(s => [s.id, s]));
  const after = async msg => { if (msg) toast(msg); await refreshMe(); reviewPage(); };
  const decide = (id, body) => api(`/api/review/${id}`, { method: 'POST', body }).then(() => after()).catch(fail);
  $$('[data-ok]', el).forEach(b => b.onclick = () => decide(b.dataset.ok, { action: 'approve' }));
  $$('[data-re]', el).forEach(s => s.onchange = () => s.value && decide(s.dataset.re, { action: 'reclassify', state: s.value }));
  $$('[data-reopen]', el).forEach(b => b.onclick = () => decide(b.dataset.reopen, { action: 'reopen' }));
  $$('[data-note]', el).forEach(b => b.onclick = () => formModal('Add a note', field('Note', `<textarea name="note" placeholder="Why this decision? e.g. supervisor confirmed he was on a work call">${esc(byId[b.dataset.note].note || '')}</textarea>`),
    async fd => { await api(`/api/review/${b.dataset.note}`, { method: 'POST', body: { action: 'note', note: fd.get('note') } }); after('Note saved'); }));
  $$('[data-play]', el).forEach(b => b.onclick = () => playClip(byId[b.dataset.play]));
  $$('[data-hist]', el).forEach(b => b.onclick = async () => {
    const h = await api(`/api/review/${b.dataset.hist}/history`);
    modal(`<h3>Decision history</h3><p class="muted small">Immutable — entries cannot be edited or deleted.</p><table class="t"><tbody>${h.map(a => `<tr><td class="small muted">${fmtTs(a.created_at)}</td><td>${esc(a.user_label)}</td><td>${esc(a.action.replace('review.', ''))}</td>
      <td>${a.after?.reviewed_state ? stateChip(a.after.reviewed_state) : ''}${a.after?.note ? ` <i class="small">“${esc(a.after.note)}”</i>` : ''}</td></tr>`).join('')}</tbody></table><div class="mfoot"><button class="btn" data-close>${t('close')}</button></div>`, { size: 'mid' });
  });
  const sel = () => $$('[data-sel]:checked', el).map(c => +c.dataset.sel);
  const upd = () => { const n = sel().length; $('#selcount', el) && ($('#selcount', el).textContent = `${n} selected`); ['#bulk-approve', '#bulk-state'].forEach(x => $(x, el) && ($(x, el).disabled = !n)); };
  $$('[data-sel]', el).forEach(c => c.onchange = upd);
  $('#all', el)?.addEventListener('change', e => { $$('[data-sel]', el).forEach(c => c.checked = e.target.checked); upd(); });
  const bulk = async body => {
    try { const r = await api('/api/review/bulk', { method: 'POST', body: { ids: sel(), similar: $('#similar', el).checked, ...body } }); after(`${r.count} item(s) updated`); } catch (e) { fail(e); }
  };
  $('#bulk-approve', el)?.addEventListener('click', () => bulk({ action: 'approve' }));
  $('#bulk-state', el)?.addEventListener('change', e => e.target.value && bulk({ action: 'reclassify', state: e.target.value }));
}

function playClip(s) {
  const pad = 2, from = Math.max(0, s.start - pad), to = s.end + pad;
  const m = modal(`<div class="row" style="margin-bottom:10px"><h3 style="margin:0">${esc(s.person)} · ${clock(s.start)}–${clock(s.end)}</h3><span class="spacer"></span>${stateChip(s.effective_state)}</div>
    <div class="stage"><video src="/api/videos/${s.video_id}/stream#t=${from}" controls autoplay muted playsinline></video></div>
    <p class="faint small">${esc(s.flag_reason || '')} — loops the flagged span with ${pad}s either side.</p><div class="mfoot"><button class="btn" data-close>${t('close')}</button></div>`);
  const vid = $('video', m);
  vid.addEventListener('timeupdate', () => { if (vid.currentTime > to) vid.currentTime = from; });
  vid.onerror = () => toast('Footage is no longer available (retention policy).', true);
}
