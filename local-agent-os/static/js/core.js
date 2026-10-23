/* Núcleo compartido: utilidades, API, streaming, navegación y avisos. */

const APP = {
  model: '',          // modelo por defecto (maestro)
  models: [],         // modelos disponibles en Ollama
  section: 'projects',
  agentNames: new Map(),   // id → nombre legible (para el feed)
};

// ── Utilidades ─────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const trunc = (s, n) => (s = String(s ?? ''), s.length > n ? s.slice(0, n) + '…' : s);

function eventMs(ts) {
  if (!ts) return Date.now();
  if (typeof ts === 'number') return ts < 1e12 ? ts * 1000 : ts;
  const parsed = Date.parse(ts);
  return Number.isNaN(parsed) ? Date.now() : parsed;
}
const LOCALE = () => (I18N.lang === 'en' ? 'en-GB' : 'es');
const fmtTime = (ts) => new Date(eventMs(ts)).toLocaleTimeString(LOCALE(), { hour: '2-digit', minute: '2-digit', second: '2-digit' });
const fmtDate = (ts) => new Date(eventMs(ts)).toLocaleString(LOCALE(), { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
const nowHM = () => new Date().toLocaleTimeString(LOCALE(), { hour: '2-digit', minute: '2-digit' });

// "agent-os/action-planner:v1" → "v1"; "qwen3-coder:30b" → "qwen3-coder:30b"
const modelLabel = (m) => {
  if (!m) return '—';
  if (m.startsWith('agent-os/')) return 'alumno ' + (m.split(':')[1] || '');
  return m;
};

// Nombres legibles: el id "constructor" choca con Object.prototype.constructor
// en un objeto normal ({}), por eso se usa un Map.
function agentName(id) { return APP.agentNames.get(id) || id || 'Sistema'; }

const stripThink = (s) => s.replace(/<think>[\s\S]*?<\/think>/gi, '').trimStart();

function summarizeOutput(output) {
  if (!output) return '';
  if (typeof output === 'string') return output;
  if (output.summary) return output.summary;
  if (output.error) return output.error;
  if (output.status) return `estado: ${output.status}`;
  const keys = Object.keys(output).slice(0, 3);
  return keys.length ? `salida: ${keys.join(', ')}` : '';
}

const STATUS_LABEL = {
  draft: 'borrador', planning: 'planificando', building: 'construyendo', ready: 'listo',
  failed: 'falló', running: 'en curso', completed: 'completado', blocked: 'bloqueado',
  pending: 'pendiente', scheduled: 'listo para correr',
};
const statusLabel = (s) => STATUS_LABEL[s] || s || '—';
const statusPill = (s) => `<span class="pill pill-${esc(s || 'draft')}">${esc(statusLabel(s))}</span>`;

// ── API ────────────────────────────────────────────────────
async function apiFetch(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = await res.text();
    try { detail = JSON.parse(detail).detail || detail; } catch { /* texto plano */ }
    throw new Error(detail);
  }
  return res.json();
}
const apiGet = (p) => apiFetch(p);
const apiDel = (p) => apiFetch(p, { method: 'DELETE' });
const apiPost = (p, b = {}) => apiFetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
const apiPut = (p, b) => apiFetch(p, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
const enc = encodeURIComponent;

// Streaming SSE (data: {chunk|done|error}) — chats con agentes, PM y Laboratorio.
async function streamSSE(path, body, onChunk) {
  const res = await fetch(path, {
    // El idioma de la interfaz viaja con cada chat: el agente responde en él.
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lang: I18N.lang, ...body }),
  });
  if (!res.ok) {
    let detail = await res.text();
    try { detail = JSON.parse(detail).detail || detail; } catch { /* texto */ }
    throw new Error(detail);
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const line = buf.slice(0, idx); buf = buf.slice(idx + 2);
      if (!line.startsWith('data: ')) continue;
      let d; try { d = JSON.parse(line.slice(6)); } catch { continue; }
      if (d.chunk) onChunk(d.chunk);
      if (d.error) throw new Error(d.error);
      if (d.done) return;
    }
  }
}

// ── Avisos ─────────────────────────────────────────────────
function toast(text, kind = 'info') {
  const box = $('toasts');
  const el = document.createElement('div');
  el.className = `toast toast-${kind}`;
  el.textContent = text;
  box.appendChild(el);
  setTimeout(() => el.classList.add('out'), 3800);
  setTimeout(() => el.remove(), 4300);
}

// ── Navegación: áreas y pestañas ───────────────────────────
const SECTION_LOADERS = Object.create(null);   // área → función que la carga al entrar

function showSection(name) {
  APP.section = name;
  document.querySelectorAll('.nav-item').forEach((b) => b.classList.toggle('active', b.dataset.section === name));
  document.querySelectorAll('.section').forEach((s) => s.classList.toggle('hidden', s.id !== `sec-${name}`));
  try { localStorage.setItem('paradax.section', name); } catch { /* sin storage */ }
  SECTION_LOADERS[name]?.();
}

// Pestañas: <div class="tabs" data-tabs="grupo"><button data-tab="x"> + paneles [data-panel="grupo:x"]
function setupTabs(root = document) {
  root.querySelectorAll('.tabs[data-tabs]').forEach((bar) => {
    bar.querySelectorAll('[data-tab]').forEach((btn) => btn.addEventListener('click', () => selectTab(bar.dataset.tabs, btn.dataset.tab)));
  });
}
const TAB_HOOKS = Object.create(null);   // "grupo:tab" → función al abrir
function selectTab(group, tab) {
  const bar = document.querySelector(`.tabs[data-tabs="${group}"]`);
  bar?.querySelectorAll('[data-tab]').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll(`[data-panel^="${group}:"]`).forEach((p) => p.classList.toggle('hidden', p.dataset.panel !== `${group}:${tab}`));
  TAB_HOOKS[`${group}:${tab}`]?.();
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 160) + 'px';
}

// Enter envía, Shift+Enter salta de línea.
function onEnterSend(textarea, send) {
  textarea.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
  textarea.addEventListener('input', () => autoResize(textarea));
}

// Burbuja de chat (siempre texto, nunca HTML: lo que diga un modelo no se interpreta).
function chatBubble(box, role, text = '', meta = '') {
  const row = document.createElement('div');
  row.className = `msg msg-${role}`;
  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  bubble.textContent = text;
  row.appendChild(bubble);
  if (meta) {
    const m = document.createElement('div');
    m.className = 'msg-meta';
    m.textContent = meta;
    row.appendChild(m);
  }
  box.appendChild(row);
  box.scrollTop = box.scrollHeight;
  return bubble;
}

// Markdown mínimo y seguro para el Archivo: se escapa TODO primero y luego se
// aplican unas pocas reglas (títulos, listas, tablas, código, negrita).
function renderMarkdown(md) {
  const lines = esc(md).split('\n');
  const out = [];
  let inCode = false, list = null, table = [], para = [], item = null;
  const inline = (s) => s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,;:]|$)/g, '$1<em>$2</em>');
  const flushPara = () => { if (para.length) { out.push(`<p>${inline(para.join(' '))}</p>`); para = []; } };
  const flushItem = () => { if (item !== null) { out.push(`<li>${inline(item)}</li>`); item = null; } };
  const flushList = () => { flushItem(); if (list) { out.push(`</${list}>`); list = null; } };
  const flushTable = () => {
    if (!table.length) return;
    const rows = table.filter((r) => !/^\|\s*:?-/.test(r));
    out.push('<table>' + rows.map((r, i) => {
      const cells = r.replace(/^\||\|$/g, '').split('|').map((c) => inline(c.trim()));
      const tag = i === 0 ? 'th' : 'td';
      return `<tr>${cells.map((c) => `<${tag}>${c}</${tag}>`).join('')}</tr>`;
    }).join('') + '</table>');
    table = [];
  };
  const flushAll = () => { flushPara(); flushList(); flushTable(); };
  for (const raw of lines) {
    if (raw.startsWith('```')) { flushAll(); out.push(inCode ? '</pre>' : '<pre>'); inCode = !inCode; continue; }
    if (inCode) { out.push(raw); continue; }
    if (raw.startsWith('|')) { flushPara(); flushList(); table.push(raw); continue; }
    flushTable();
    const h = raw.match(/^(#{1,4}) (.*)$/);
    if (h) { flushAll(); out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); continue; }
    const li = raw.match(/^(\s*)(?:[-*]|(\d+)\.) (.*)$/);
    if (li && li[1].length < 2) {
      flushPara();
      const kind = li[2] ? 'ol' : 'ul';
      if (list !== kind) { flushList(); out.push(`<${kind}>`); list = kind; }
      flushItem(); item = li[3]; continue;
    }
    if (/^---+$/.test(raw.trim())) { flushAll(); out.push('<hr>'); continue; }
    if (!raw.trim()) { flushPara(); flushList(); continue; }
    if (item !== null) { item += ' ' + raw.trim(); continue; }
    para.push(raw.trim());
  }
  flushAll();
  if (inCode) out.push('</pre>');
  return out.join('\n');
}
