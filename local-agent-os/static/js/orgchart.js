/* Organigrama por niveles: cada nivel es una franja horizontal con su nombre
   a la izquierda (Dirección, Team Constructor, Ejecución, Equipo…).
   renderOrg(svg, org, { onNode }) — org viene de /api/projects/{id}/org. */

const ORG = { NW: 150, NH: 54, GX: 18, BAND: 122, LABEL: 160, TOP: 8, PAD: 30 };
const SVGNS = 'http://www.w3.org/2000/svg';

function svgEl(tag, attrs = {}, text) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (text != null) el.textContent = text;
  return el;
}

function renderOrg(svg, org, { onNode } = {}) {
  svg.innerHTML = `
    <defs>
      <marker id="arrMando" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0.5 L7,4 L0,7.5" fill="none" stroke="var(--edge)" stroke-width="1.3"/></marker>
      <marker id="arrDatos" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0.5 L7,4 L0,7.5" fill="none" stroke="var(--c-team)" stroke-width="1.3"/></marker>
      <pattern id="hazard" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="4" height="8" fill="var(--danger)"/>
      </pattern>
    </defs>`;
  const levels = org.levels.filter((l) => org.nodes.some((n) => n.level === l.id) || l.id === 'ejecutan');
  const rows = levels.map((l) => org.nodes.filter((n) => n.level === l.id));
  const maxCount = Math.max(1, ...rows.map((r) => r.length));
  const innerW = maxCount * ORG.NW + (maxCount - 1) * ORG.GX;
  const W = ORG.LABEL + innerW + 40;
  const H = ORG.TOP + levels.length * ORG.BAND;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.style.minWidth = `${Math.min(W, 860)}px`;
  svg.style.maxWidth = `${W}px`;

  const pos = new Map();
  const bands = svgEl('g', { class: 'org-bands' });
  const edgesG = svgEl('g', { class: 'org-edges' });
  const nodesG = svgEl('g', { class: 'org-nodes' });
  svg.append(bands, edgesG, nodesG);

  levels.forEach((lvl, i) => {
    const top = ORG.TOP + i * ORG.BAND;
    const y = top + ORG.PAD;
    bands.appendChild(svgEl('rect', { x: 0, y: top, width: W, height: ORG.BAND - 8, class: `band band-${lvl.id}`, rx: 6 }));
    bands.appendChild(svgEl('text', { x: 16, y: top + 26, class: 'band-label' }, tr(lvl.label)));
    const desc = svgEl('text', { x: 16, y: top + 44, class: 'band-desc' });
    wrapText(desc, tr(lvl.description), 21, 16, 14);
    bands.appendChild(desc);
    const row = rows[i];
    const rowW = row.length * ORG.NW + Math.max(0, row.length - 1) * ORG.GX;
    const x0 = ORG.LABEL + (innerW - rowW) / 2;
    row.forEach((n, k) => pos.set(n.id, { x: x0 + k * (ORG.NW + ORG.GX), y, n, col: k, row: i }));
    if (!row.length) {
      bands.appendChild(svgEl('text', { x: ORG.LABEL + innerW / 2, y: y + ORG.NH / 2 + 4, class: 'band-empty', 'text-anchor': 'middle' },
        'Sin agentes todavía: construye el equipo'));
    }
  });

  for (const e of org.edges) {
    const a = pos.get(e.from), b = pos.get(e.to);
    if (!a || !b) continue;
    let d;
    if (a.row === b.row) {
      const left = a.x < b.x;
      const sx = left ? a.x + ORG.NW : a.x, tx = left ? b.x : b.x + ORG.NW;
      const adjacent = Math.abs(a.col - b.col) === 1;
      if (adjacent) {
        d = `M ${sx} ${a.y + ORG.NH / 2} L ${tx} ${b.y + ORG.NH / 2}`;
      } else {
        const ax = a.x + ORG.NW / 2, bx = b.x + ORG.NW / 2, yb = a.y + ORG.NH;
        d = `M ${ax} ${yb} C ${ax} ${yb + 26}, ${bx} ${yb + 26}, ${bx} ${yb}`;
      }
    } else {
      const down = a.row < b.row;
      const sx = a.x + ORG.NW / 2, sy = down ? a.y + ORG.NH : a.y;
      const tx = b.x + ORG.NW / 2, ty = down ? b.y : b.y + ORG.NH;
      const my = (sy + ty) / 2;
      d = `M ${sx} ${sy} C ${sx} ${my}, ${tx} ${my}, ${tx} ${ty}`;
    }
    const kind = e.kind === 'datos' ? 'datos' : 'mando';
    const path = svgEl('path', { d, class: `edge edge-${kind}`, 'marker-end': `url(#arr${kind === 'datos' ? 'Datos' : 'Mando'})`, 'data-edge': `${e.from}->${e.to}` });
    path.appendChild(svgEl('title', {}, `${agentName(e.from)} → ${agentName(e.to)}${e.label ? ': ' + e.label : ''}`));
    edgesG.appendChild(path);
  }

  for (const { x, y, n } of pos.values()) {
    const blocked = n.status === 'blocked';
    const q = (n.quarantined || []).length > 0;
    const g = svgEl('g', {
      class: `onode lvl-${n.level}${blocked ? ' blocked' : ''}${q ? ' quarantined' : ''}${n.specialized ? ' student' : ''}`,
      transform: `translate(${x},${y})`, tabindex: 0, role: 'button', 'data-id': n.id,
      'aria-label': `${n.name}: ${n.role || ''}`,
    });
    g.appendChild(svgEl('title', {}, [n.role, q ? `Versiones en cuarentena: ${n.quarantined.join(', ')}` : '', blocked ? `Faltan: ${(n.missing || []).join(', ')}` : ''].filter(Boolean).join('\n')));
    g.appendChild(svgEl('rect', { class: 'node-ring', x: -4, y: -4, width: ORG.NW + 8, height: ORG.NH + 8, rx: 10 }));
    g.appendChild(svgEl('rect', { class: 'node-box', width: ORG.NW, height: ORG.NH, rx: 7 }));
    g.appendChild(svgEl('rect', { class: 'node-stripe', width: 4, height: ORG.NH - 16, x: 0, y: 8, rx: 2 }));
    g.appendChild(svgEl('text', { x: 14, y: 23, class: 'node-name' }, trunc(tr(n.name), 18)));
    const sub = blocked ? `faltan: ${(n.missing || []).join(', ')}` : modelLabel(n.model);
    g.appendChild(svgEl('text', { x: 14, y: 42, class: `node-sub${blocked ? ' warn' : ''}` }, trunc(tr(sub), 21)));
    if (q) {
      g.appendChild(svgEl('rect', { class: 'node-hazard', x: ORG.NW - 28, y: 0, width: 28, height: 6, rx: 2 }));
    }
    if (n.specialized) g.appendChild(svgEl('circle', { class: 'node-student', cx: ORG.NW - 12, cy: ORG.NH - 12, r: 4 }));
    const activate = () => onNode?.(n);
    g.addEventListener('click', activate);
    g.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); activate(); } });
    nodesG.appendChild(g);
  }
}

function wrapText(textEl, text, maxChars, x, lineH) {
  const words = String(text || '').split(/\s+/);
  let line = '', dy = 0;
  const lines = [];
  for (const w of words) {
    if ((line + ' ' + w).trim().length > maxChars) { lines.push(line.trim()); line = w; } else line += ' ' + w;
  }
  if (line.trim()) lines.push(line.trim());
  lines.slice(0, 3).forEach((l, i) => {
    textEl.appendChild(svgEl('tspan', { x, dy: i === 0 ? 0 : lineH }, l));
    dy += lineH;
  });
}

// Estado en vivo de un run: anillos en los nodos y flujo en las aristas.
function setOrgLive(svg, live) {
  svg.querySelectorAll('.onode').forEach((g) => {
    const id = g.dataset.id;
    g.classList.toggle('active', live.active.has(id));
    g.classList.toggle('done', live.done.has(id) && !live.active.has(id));
    g.classList.toggle('failed', live.failed.has(id));
  });
  svg.querySelectorAll('.edge').forEach((p) => {
    const [, to] = (p.dataset.edge || '').split('->');
    p.classList.toggle('flow', live.active.has(to));
  });
}
