/* Canvas overlay on an <img> or <video>: zone polygons (draw / drag vertices), detection boxes on the
   reference frame (click to pick a person), per-track boxes during playback, and face blur. */
import { $$, esc, icon, ZONE_COLORS, zoneLabel, STATE_COLOR, stateLabel, t } from './core.js';

export class Overlay {
  constructor(stage, media, { zones = [], onChange = () => { }, onPick = null, blur = false } = {}) {
    Object.assign(this, { stage, media, zones, onChange, onPick, blur, editing: false, draft: null, draftType: 'work',
      tracks: null, labels: {}, removed: new Set(), highlight: null, showBoxes: true, mouse: null, drag: null, staticBoxes: [] });
    this.canvas = document.createElement('canvas');
    stage.appendChild(this.canvas);
    this.ctx = this.canvas.getContext('2d');
    this.ro = new ResizeObserver(() => this.resize()); this.ro.observe(media);
    this.canvas.addEventListener('mousedown', e => this.down(e));
    this.canvas.addEventListener('dblclick', e => { e.preventDefault(); this.finish(); });
    this.canvas.addEventListener('contextmenu', e => { if (this.editing) { e.preventDefault(); this.draft = null; this.draw(); } });
    this._move = e => this.move(e);
    this._up = () => { if (this.drag) { this.drag = null; this.changed(); } };
    this._key = e => {
      if (!this.editing || ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
      if (e.key === 'Escape') { this.draft = null; this.draw(); }
      if (e.key === 'Enter') this.finish();
      if (e.key === 'Backspace' && this.draft) { this.draft.points.pop(); if (!this.draft.points.length) this.draft = null; this.draw(); e.preventDefault(); }
    };
    window.addEventListener('mousemove', this._move); window.addEventListener('mouseup', this._up); window.addEventListener('keydown', this._key);
    const loop = () => { if (this.dead) return; if (this.media.tagName === 'VIDEO' && !this.media.paused) this.draw(); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
    if (media.tagName === 'VIDEO') { media.addEventListener('seeked', () => this.draw()); media.addEventListener('loadeddata', () => this.resize()); }
    else media.addEventListener('load', () => this.resize());
    this.pointer();
  }
  destroy() { this.dead = true; this.ro.disconnect(); window.removeEventListener('mousemove', this._move); window.removeEventListener('mouseup', this._up); window.removeEventListener('keydown', this._key); this.canvas.remove(); }
  pointer() {
    const pick = !this.editing && this.onPick && this.staticBoxes.length;
    this.canvas.style.pointerEvents = this.editing || pick ? 'auto' : 'none';
    this.stage.classList.toggle('editing', this.editing);
    this.stage.classList.toggle('pick', !!pick);
  }
  setEditing(on) { this.editing = on; this.draft = null; this.pointer(); this.draw(); }
  setStatic(boxes) { this.staticBoxes = boxes; this.pointer(); this.draw(); }
  changed() { this.onChange(this.zones); this.draw(); }
  resize() {
    const r = this.media.getBoundingClientRect(), dpr = devicePixelRatio || 1;
    if (!r.width) return;
    this.w = r.width; this.h = r.height;
    this.canvas.width = r.width * dpr; this.canvas.height = r.height * dpr;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.draw();
  }
  pos(e) { const r = this.canvas.getBoundingClientRect(); return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))]; }
  near(a, b, px = 10) { return Math.hypot((a[0] - b[0]) * this.w, (a[1] - b[1]) * this.h) < px; }
  down(e) {
    if (e.button !== 0) return;
    const p = this.pos(e);
    if (!this.editing) {
      if (!this.onPick) return;
      const hit = [...this.staticBoxes].reverse().find(b => p[0] >= b.box[0] && p[0] <= b.box[2] && p[1] >= b.box[1] && p[1] <= b.box[3]);
      if (hit) this.onPick(hit);
      return;
    }
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
    this.zones.push({ name: `${zoneLabel(this.draft.type)} ${n}`, type: this.draft.type, points: this.draft.points });
    this.draft = null; this.changed();
  }
  boxesAt(time) {
    const out = [];
    for (const [tid, tr] of Object.entries(this.tracks || {})) {
      const s = tr.s;
      let lo = 0, hi = s.length - 1;
      if (hi < 0 || time < s[0][0] - 0.3 || time > s[hi][0] + 0.3) continue;
      while (lo < hi) { const mid = (lo + hi) >> 1; if (s[mid][0] < time) lo = mid + 1; else hi = mid; }
      const c = lo > 0 && Math.abs(s[lo - 1][0] - time) < Math.abs(s[lo][0] - time) ? s[lo - 1] : s[lo];
      if (Math.abs(c[0] - time) <= 0.3) out.push([tr.root, c, tr.removed]);
    }
    return out;
  }
  label(ctx, text, x, y, col) {
    const tw = ctx.measureText(text).width + 12;
    ctx.fillStyle = col; ctx.beginPath(); ctx.roundRect?.(x, y - 19, tw, 19, 4) ?? ctx.rect(x, y - 19, tw, 19); ctx.fill();
    ctx.fillStyle = '#0b0f15'; ctx.fillText(text, x + 6, y - 5.5);
  }
  blurBox(x1, y1, x2, y2) {
    // Blur the head area (top quarter of the person box) straight from the video frame.
    const { ctx, w, h, media } = this;
    const bw = (x2 - x1), hh = Math.min(bw * 1.1, (y2 - y1) * 0.28);
    const sx = (x1 + bw * 0.1) * media.videoWidth, sy = y1 * media.videoHeight, sw = bw * 0.8 * media.videoWidth, sh = hh * media.videoHeight;
    if (sw < 2 || sh < 2) return;
    ctx.save(); ctx.filter = 'blur(10px)';
    ctx.drawImage(media, sx, sy, sw, sh, (x1 + bw * 0.1) * w, y1 * h, bw * 0.8 * w, hh * h);
    ctx.restore();
  }
  draw() {
    const { ctx, w, h } = this;
    if (!w) return;
    ctx.clearRect(0, 0, w, h);
    const poly = (pts, close) => { ctx.beginPath(); pts.forEach(([x, y], i) => i ? ctx.lineTo(x * w, y * h) : ctx.moveTo(x * w, y * h)); if (close) ctx.closePath(); };
    ctx.font = '600 12px "General Sans", system-ui, sans-serif';
    const quiet = this.staticBoxes.length > 0;  // picking people: zones stay as faint context
    for (const z of this.zones) {
      const col = z.color || ZONE_COLORS[z.type];
      poly(z.points, true);
      ctx.fillStyle = col + (quiet ? '10' : '24'); ctx.fill();
      ctx.globalAlpha = quiet ? 0.35 : 1;
      ctx.lineWidth = 2; ctx.strokeStyle = col; ctx.setLineDash(z.type === 'exclusion' ? [7, 5] : []); ctx.stroke(); ctx.setLineDash([]);
      ctx.globalAlpha = 1;
      const [x, y] = z.points.reduce((a, p) => (p[1] < a[1] ? p : a));
      if (!quiet) this.label(ctx, z.name, x * w, Math.max(19, y * h), col);
      if (this.editing) z.points.forEach(([px, py]) => { ctx.fillStyle = '#fff'; ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(px * w, py * h, 5, 0, 7); ctx.fill(); ctx.stroke(); });
    }
    if (this.draft) {
      const col = ZONE_COLORS[this.draft.type];
      poly(this.mouse ? [...this.draft.points, this.mouse] : this.draft.points, false);
      ctx.setLineDash([6, 4]); ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.stroke(); ctx.setLineDash([]);
      this.draft.points.forEach(([px, py], i) => { ctx.beginPath(); ctx.arc(px * w, py * h, i ? 4 : 7, 0, 7); ctx.fillStyle = i ? col : '#fff'; ctx.fill(); });
    }
    // reference-frame detections
    for (const b of this.staticBoxes) {
      const [x1, y1, x2, y2] = b.box;
      const col = b.removed ? '#5a6577' : b.selected ? '#ffffff' : '#eeb23e';
      ctx.globalAlpha = b.removed ? 0.6 : 1;
      ctx.lineWidth = b.selected ? 3 : 2; ctx.strokeStyle = col; ctx.setLineDash(b.removed ? [5, 4] : []);
      ctx.strokeRect(x1 * w, y1 * h, (x2 - x1) * w, (y2 - y1) * h); ctx.setLineDash([]);
      this.label(ctx, b.label, x1 * w, Math.max(19, y1 * h), col);
      ctx.globalAlpha = 1;
    }
    // playback boxes
    if (this.tracks && this.media.tagName === 'VIDEO' && this.media.readyState >= 2) {
      for (const [root, [, x1, y1, x2, y2, st, phone], removed] of this.boxesAt(this.media.currentTime)) {
        if (this.blur) this.blurBox(x1, y1, x2, y2);
        if (!this.showBoxes || removed) continue;
        const dim = this.highlight != null && this.highlight !== root;
        const col = STATE_COLOR[st] || '#9aa6b5';
        ctx.globalAlpha = dim ? 0.22 : 1;
        ctx.lineWidth = this.highlight === root ? 3 : 2; ctx.strokeStyle = col;
        ctx.strokeRect(x1 * w, y1 * h, (x2 - x1) * w, (y2 - y1) * h);
        this.label(ctx, `${this.labels[root] || 'Person ' + root} · ${st ? stateLabel(st) : '—'}${phone ? ' 📱' : ''}`, x1 * w, Math.max(19, y1 * h), col);
        ctx.globalAlpha = 1;
      }
    }
  }
}

export function zoneTools(ov, bar, list, { onChange = () => { } } = {}) {
  bar.innerHTML = `<span class="muted small">Draw</span>
    ${Object.keys(ZONE_COLORS).map(z => `<button class="btn sm ${z === ov.draftType ? 'on' : ''}" data-type="${z}"><span class="dot" style="background:${ZONE_COLORS[z]}"></span>${esc(zoneLabel(z))}</button>`).join('')}
    <span class="faint small">Click to add points · click the first point or Enter to close · drag a corner to adjust · Esc cancels</span>`;
  $$('[data-type]', bar).forEach(b => b.onclick = () => {
    ov.draftType = b.dataset.type; if (ov.draft) ov.draft.type = b.dataset.type;
    $$('[data-type]', bar).forEach(x => x.classList.toggle('on', x === b)); ov.draw();
  });
  const render = () => {
    list.innerHTML = ov.zones.length ? ov.zones.map((z, i) => `<div class="zone-item"><span class="dot" style="background:${z.color || ZONE_COLORS[z.type]}"></span>
      <input type="text" value="${esc(z.name)}" data-i="${i}" data-k="name" aria-label="Zone name"><select data-i="${i}" data-k="type" aria-label="Zone type">${Object.keys(ZONE_COLORS).map(x => `<option value="${x}" ${x === z.type ? 'selected' : ''}>${esc(zoneLabel(x))}</option>`).join('')}</select>
      <button class="btn xs ghost danger" data-del="${i}" title="${t('delete')}">${icon('trash')}</button></div>`).join('')
      : '<p class="faint small" style="margin:0">No zones yet. Pick a zone type and click on the frame. Work zones count toward working time; break zones mark breaks; exclusion zones are flagged and left out.</p>';
    $$('[data-k]', list).forEach(el => el.oninput = () => { ov.zones[el.dataset.i][el.dataset.k] = el.value; ov.draw(); onChange(); if (el.tagName === 'SELECT') render(); });
    $$('[data-del]', list).forEach(b => b.onclick = () => { ov.zones.splice(+b.dataset.del, 1); ov.changed(); });
  };
  const prev = ov.onChange;
  ov.onChange = z => { prev(z); render(); onChange(); };
  render();
}
