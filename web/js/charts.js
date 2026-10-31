/* Small dependency-free SVG charts: stacked bars (by state), donut, sparkline. */
import { esc, STATES, STATE_COLOR, stateLabel, hm, fmtDay } from './core.js';

let tip;
function showTip(e, html) {
  if (!tip) { tip = document.createElement('div'); tip.className = 'tip'; document.body.appendChild(tip); }
  tip.innerHTML = html; tip.hidden = false;
  const r = tip.getBoundingClientRect();
  tip.style.left = Math.min(innerWidth - r.width - 10, e.clientX + 14) + 'px';
  tip.style.top = Math.max(10, e.clientY - r.height - 10) + 'px';
}
const hideTip = () => { if (tip) tip.hidden = true; };

export function stackedBars(el, data, { height = 220 } = {}) {
  const W = el.clientWidth || 600, H = height, pl = 36, pb = 22, pt = 8;
  const totals = data.map(d => STATES.reduce((a, s) => a + d[s], 0));
  const maxH = Math.max(1, ...totals) / 3600;
  const step = maxH > 20 ? 10 : maxH > 8 ? 4 : maxH > 2 ? 1 : maxH > 0.5 ? 0.25 : 0.05;
  const top = Math.ceil(maxH / step) * step || step;
  const y = v => pt + (H - pt - pb) * (1 - v / top);
  const bw = (W - pl) / data.length;
  let g = '';
  for (let v = 0; v <= top + 1e-9; v += step) g += `<line class="grid-l" x1="${pl}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/><text x="${pl - 6}" y="${y(v) + 4}" text-anchor="end">${+v.toFixed(2)}h</text>`;
  data.forEach((d, i) => {
    let acc = 0;
    const x = pl + i * bw + bw * 0.18, w = bw * 0.64;
    STATES.forEach(s => {
      const v = d[s] / 3600;
      if (v <= 0) return;
      g += `<rect x="${x}" y="${y(acc + v)}" width="${w}" height="${Math.max(0.5, y(acc) - y(acc + v))}" fill="${STATE_COLOR[s]}" rx="1.5"/>`;
      acc += v;
    });
    g += `<rect x="${pl + i * bw}" y="${pt}" width="${bw}" height="${H - pt - pb}" fill="transparent" data-i="${i}"/>`;
    if (data.length <= 16 || i % Math.ceil(data.length / 10) === 0) g += `<text x="${x + w / 2}" y="${H - 6}" text-anchor="middle">${esc(fmtDay(d.date).slice(0, 6))}</text>`;
  });
  el.innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${H}" height="${H}">${g}</svg>`;
  el.querySelectorAll('[data-i]').forEach(r => {
    r.addEventListener('mousemove', e => {
      const d = data[+r.dataset.i];
      showTip(e, `<div style="font-weight:600;margin-bottom:4px">${esc(fmtDay(d.date))}</div>` +
        STATES.filter(s => d[s]).map(s => `<div class="tr"><span class="dot" style="background:${STATE_COLOR[s]}"></span>${esc(stateLabel(s))}<b>${hm(d[s])}</b></div>`).join('') || 'No footage');
    });
    r.addEventListener('mouseleave', hideTip);
  });
}

export function donut(totals, { size = 150, center = '', sub = '' } = {}) {
  const sum = STATES.reduce((a, s) => a + (totals[s] || 0), 0) || 1;
  const R = size / 2 - 8, C = 2 * Math.PI * R;
  let off = 0, arcs = '';
  STATES.forEach(s => {
    const v = (totals[s] || 0) / sum;
    if (v <= 0) return;
    arcs += `<circle r="${R}" cx="${size / 2}" cy="${size / 2}" fill="none" stroke="${STATE_COLOR[s]}" stroke-width="14" stroke-dasharray="${v * C} ${C}" stroke-dashoffset="${-off * C}" transform="rotate(-90 ${size / 2} ${size / 2})"><title>${esc(stateLabel(s))}: ${hm(totals[s])}</title></circle>`;
    off += v;
  });
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" style="flex:none">
    <circle r="${R}" cx="${size / 2}" cy="${size / 2}" fill="none" stroke="var(--surface-3)" stroke-width="14"/>${arcs}
    <text x="50%" y="48%" text-anchor="middle" style="fill:var(--text);font-size:24px;font-weight:600">${esc(center)}</text>
    <text x="50%" y="62%" text-anchor="middle" style="fill:var(--faint);font-size:11px">${esc(sub)}</text></svg>`;
}

export function legendRows(totals) {
  const sum = STATES.reduce((a, s) => a + (totals[s] || 0), 0) || 1;
  return `<div class="donut-legend">${STATES.map(s => `<div><span class="dot" style="background:${STATE_COLOR[s]}"></span><span>${esc(stateLabel(s))}</span><span class="v">${hm(totals[s])}</span><span class="p">${Math.round(100 * (totals[s] || 0) / sum)}%</span></div>`).join('')}</div>`;
}

export function spark(values, { w = 90, h = 30, color = '#eeb23e' } = {}) {
  if (!values.length) return '';
  const max = Math.max(1e-9, ...values);
  const pts = values.map((v, i) => `${(i / Math.max(1, values.length - 1)) * w},${h - 2 - (v / max) * (h - 4)}`).join(' ');
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
}
