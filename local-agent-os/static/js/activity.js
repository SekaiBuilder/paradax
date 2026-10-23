/* Área Actividad: eventos en vivo, run en curso, terminal de agentes y
   peticiones. También reparte cada evento SSE a las demás áreas. */

const ACT = { es: null, steps: [], runStart: 0, timer: null, events: [], unseen: 0 };

const FEED_COLOR = { ok: 'var(--ok)', fail: 'var(--danger)', warn: 'var(--warn)', info: 'var(--text-2)', run: 'var(--c-proj)' };

function connectEvents() {
  ACT.es?.close();
  const es = new EventSource('/api/events');
  ACT.es = es;
  es.onopen = () => $('liveDot').classList.add('on');
  es.onerror = () => $('liveDot').classList.remove('on');
  es.onmessage = (e) => {
    let ev; try { ev = JSON.parse(e.data); } catch { return; }
    handleEvent(ev);
  };
}

function handleEvent(ev, replay = false) {
  ACT.events.push(ev);
  if (ACT.events.length > 200) ACT.events.shift();
  projLiveEvent(ev);
  const who = ev.agent ? agentName(ev.agent) : '';
  switch (ev.kind) {
    case 'run_started':
    case 'project_run_started':
      ACT.steps = []; ACT.runStart = Date.now(); startTimer();
      $('runTitle').textContent = ev.kind === 'run_started' ? `Media Manager: ${ev.request || 'run'}` : `Proyecto ${ev.project || ''}: ${ev.request || 'ejecución'}`;
      feed(ev.ts, 'run', ev.kind === 'run_started' ? 'Orchestrator' : 'Project Manager', `empieza: ${ev.request || ev.project || ''}`);
      break;
    case 'agent_started':
      ACT.steps.push({ agent: ev.agent, status: 'running', detail: '' });
      feed(ev.ts, 'info', who, 'trabajando…');
      break;
    case 'agent_completed': {
      const s = [...ACT.steps].reverse().find((x) => x.agent === ev.agent && x.status === 'running');
      if (s) { s.status = 'done'; s.detail = ev.summary || ''; }
      feed(ev.ts, 'ok', who, ev.summary || 'listo');
      break;
    }
    case 'agent_failed': {
      const s = [...ACT.steps].reverse().find((x) => x.agent === ev.agent && x.status === 'running');
      if (s) { s.status = 'failed'; s.detail = ev.error || 'falló'; }
      feed(ev.ts, 'fail', who, ev.error || 'falló');
      break;
    }
    case 'agent_skipped':
      ACT.steps.push({ agent: ev.agent, status: 'failed', detail: (ev.missing || []).length ? `faltan: ${ev.missing.join(', ')}` : 'omitido' });
      feed(ev.ts, 'warn', who, (ev.missing || []).length ? `omitido: faltan ${ev.missing.join(', ')}` : 'omitido');
      break;
    case 'run_finished':
    case 'project_run_finished':
      stopTimer();
      $('runTitle').textContent = ev.status === 'completed' ? 'Último run: completado' : `Último run: ${statusLabel(ev.status || 'failed')}`;
      feed(ev.ts, ev.status === 'completed' ? 'ok' : 'fail', ev.kind === 'run_finished' ? 'Orchestrator' : 'Project Manager',
        ev.status === 'completed' ? 'terminado' : `${statusLabel(ev.status || 'failed')}${ev.error ? ': ' + ev.error : ''}`);
      break;
    case 'chat_message':
      feed(ev.ts, 'info', ev.role === 'user' ? `Tú → ${who}` : who, ev.text || '');
      break;
    case 'dialogue':
      feed(ev.ts, 'info', `${agentName(ev.from)} → ${agentName(ev.to)}`, ev.text || '');
      break;
    case 'project_build_started':
      feed(ev.ts, 'run', 'Project Manager', `construye el equipo: ${ev.goal || ''}`);
      break;
    case 'agent_registered':
      feed(ev.ts, 'ok', 'Constructor', `agente listo: ${ev.name || ev.agent}`);
      break;
    case 'project_build_finished':
      feed(ev.ts, ev.status === 'ready' ? 'ok' : 'fail', 'Project Manager', ev.status === 'ready' ? `equipo listo (${(ev.agents || []).length} agentes)` : `falló: ${ev.reason || ''}`);
      break;
    default:
      return;
  }
  renderSteps();
  if (!replay && APP.section !== 'activity') { ACT.unseen++; $('actCount').textContent = ACT.unseen > 99 ? '99+' : String(ACT.unseen); }
}

function feed(ts, kind, who, text) {
  const box = $('feed');
  box.querySelector('.empty-inline')?.remove();
  const row = document.createElement('div');
  row.className = 'feed-row';
  row.innerHTML = `<time>${esc(fmtTime(ts))}</time><span class="dot" style="background:${FEED_COLOR[kind]}"></span><span><b>${esc(who)}</b> ${esc(trunc(text, 400))}</span>`;
  box.appendChild(row);
  while (box.children.length > 150) box.firstChild.remove();
  box.scrollTop = box.scrollHeight;
}

function renderSteps() {
  const box = $('runSteps');
  if (!ACT.steps.length) { box.innerHTML = '<p class="muted">Cuando se ejecute algo, aquí verás cada agente en orden.</p>'; return; }
  box.innerHTML = ACT.steps.map((s) => `
    <div class="step step-${s.status}">
      <span class="step-mark"></span><b>${esc(agentName(s.agent))}</b><span class="muted">${esc(trunc(s.detail, 90))}</span>
    </div>`).join('');
}

function startTimer() {
  stopTimer();
  ACT.timer = setInterval(() => { $('runTimer').textContent = `${((Date.now() - ACT.runStart) / 1000).toFixed(0)} s`; }, 500);
}
function stopTimer() { clearInterval(ACT.timer); ACT.timer = null; }

// ── Terminal ───────────────────────────────────────────────
async function renderTerminal() {
  let agents = [], activity = { events: [] };
  try {
    [agents, activity] = await Promise.all([
      apiGet('/api/agents?project=all').then((d) => d.agents || []),
      apiGet('/api/activity?limit=60'),
    ]);
  } catch (e) { $('termLog').innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
  const evs = [...(activity.events || []), ...ACT.events].filter((e) => e.kind).sort((a, b) => eventMs(a.ts) - eventMs(b.ts));
  const latest = new Map();
  for (const e of evs) if (e.agent) latest.set(e.agent, e);
  const stateOf = (e) => !e ? 'idle' : e.kind === 'agent_failed' ? 'failed' : e.kind === 'agent_started' ? 'running' : e.kind === 'agent_completed' ? 'done' : 'idle';
  const label = { idle: 'en espera', failed: 'falló', running: 'trabajando', done: 'terminó' };
  $('termAgents').innerHTML = agents.map((a) => {
    const st = stateOf(latest.get(a.id));
    return `<div class="term-agent st-${st}"><span class="dot"></span><b>${esc(a.name || a.id)}</b><span class="muted">${label[st]}</span></div>`;
  }).join('');
  const seen = new Set();
  $('termLog').innerHTML = evs.slice(-80).reverse().filter((e) => {
    const k = `${e.kind}|${e.agent}|${e.ts}`; if (seen.has(k)) return false; seen.add(k); return true;
  }).map((e) => `<div class="log-row ${e.kind.includes('failed') ? 'bad' : ''}"><time>${esc(fmtTime(e.ts))}</time><code>${esc(e.kind)}</code><b>${esc(e.agent ? agentName(e.agent) : 'Sistema')}</b><span>${esc(trunc(e.summary || e.error || e.request || e.text || summarizeOutput(e.output) || '', 160))}</span></div>`).join('')
    || '<p class="muted">Sin eventos recientes.</p>';
}

// ── Peticiones ─────────────────────────────────────────────
async function renderRequests() {
  try {
    const [pd, rd] = await Promise.all([apiGet('/api/projects'), apiGet('/api/runs?limit=12')]);
    const details = await Promise.all((pd.projects || []).map((p) => apiGet(`/api/projects/${enc(p.id)}`).catch(() => ({ ...p, tasks: [] }))));
    const tasks = details.flatMap((p) => (p.tasks || []).map((t) => ({ ...t, project: p.name })))
      .sort((a, b) => eventMs(b.updated_at || b.created_at) - eventMs(a.updated_at || a.created_at)).slice(0, 15);
    $('reqTasks').innerHTML = tasks.length ? tasks.map((t) => `
      <div class="row-card"><div class="rc-main"><b>${esc(t.project)}</b><span>${esc(trunc(t.request || '', 160))}</span></div>
      <div class="rc-side">${statusPill(t.status)}<span class="muted">${esc(fmtDate(t.updated_at || t.created_at))}</span></div></div>`).join('')
      : '<p class="muted">Todavía no hay peticiones.</p>';
    const runs = rd.runs || [];
    $('reqRuns').innerHTML = runs.length ? runs.map((r) => `
      <div class="row-card"><div class="rc-main"><span>${esc(trunc(r.request || r.id, 140))}</span><code>${esc(r.id)}</code></div>
      <div class="rc-side">${statusPill(r.status)}<span class="muted">${esc(fmtDate(r.updated_at || r.created_at))}</span></div></div>`).join('')
      : '<p class="muted">Sin runs registrados.</p>';
  } catch (e) { $('reqTasks').innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
}

async function renderResearchLog() {
  let entries = [];
  try { entries = (await apiGet('/api/research/log?limit=30')).entries || []; } catch { /* vacío */ }
  $('rsLog').innerHTML = entries.length ? entries.map((e) => `
    <div class="row-card"><div class="rc-main"><b>${esc(e.question)}</b>
      <span class="muted">${esc(agentName(e.agent))} · ${e.cached ? 'desde caché' : `${(e.sources || []).length} fuentes · ${e.budget?.pages ?? 0} páginas`}${(e.flagged || []).length ? ` · <span class="danger">${e.flagged.length} página(s) con inyección descartadas</span>` : ''}</span></div>
      <div class="rc-side"><span class="pill">${esc(e.mode)}</span><span class="muted">${esc(fmtDate(e.ts))}</span></div></div>`).join('')
    : '<p class="muted">Ningún agente ha investigado todavía.</p>';
}

async function runResearch() {
  const question = $('rsQuestion').value.trim();
  if (!question) return;
  const out = $('rsResult');
  out.innerHTML = '<p class="muted">Investigando…</p>';
  try {
    const r = await apiPost('/api/research', { question, mode: $('rsMode').value });
    out.innerHTML = `
      <div class="callout callout-info">${icon('info')}<span>${r.budget.searches} búsquedas · ${r.budget.pages} páginas · ${r.budget.seconds} s${r.cached ? ' · desde caché' : ''}${r.gaps.length ? ' · ' + esc(r.gaps.join('; ')) : ''}</span></div>
      ${r.excerpts.map((x) => `<blockquote class="excerpt">${esc(x.text)}<cite>${esc(x.source)}</cite></blockquote>`).join('')}
      ${r.notes.length ? `<p class="muted small">${esc(r.notes.join(' · '))}</p>` : ''}`;
  } catch (e) { out.innerHTML = `<p class="danger">${esc(e.message)}</p>`; }
  renderResearchLog();
}

function setupActivity() {
  TAB_HOOKS['act:research'] = renderResearchLog;
  $('rsGo').addEventListener('click', runResearch);
  $('rsQuestion').addEventListener('keydown', (e) => { if (e.key === 'Enter') runResearch(); });
  SECTION_LOADERS.activity = () => {
    ACT.unseen = 0; $('actCount').textContent = '';
    const tab = document.querySelector('.tabs[data-tabs="act"] .active')?.dataset.tab || 'live';
    selectTab('act', tab);
  };
  TAB_HOOKS['act:terminal'] = renderTerminal;
  TAB_HOOKS['act:requests'] = renderRequests;
  renderSteps();
}
