/* Área Proyectos: lista + espacio de trabajo de cada proyecto con pestañas
   Jerarquía · Project Manager · Equipo · Ejecuciones · Programación.
   El Media Manager aparece como proyecto integrado (pipeline fijo). */

const P = { list: [], current: null, detail: null, polling: null, schedDays: new Set(), sending: false };
const PLIVE = { runId: null, active: new Set(), done: new Set(), failed: new Set() };
const MEDIA = { id: 'media-manager', name: 'Media Manager', goal: 'GIFs y reels grabados de páginas reales', status: 'ready', builtin: true };

const isMedia = () => P.current === MEDIA.id;

async function loadProjects() {
  try { P.list = (await apiGet('/api/projects')).projects || []; } catch { P.list = []; }
  renderProjList();
  if (!P.current) {
    let last = null;
    try { last = localStorage.getItem('paradax.project'); } catch { /* sin storage */ }
    if (last && (last === MEDIA.id || P.list.some((p) => p.id === last))) openProject(last);
  }
}

function renderProjList() {
  const items = [...P.list, MEDIA];
  $('projList').innerHTML = items.map((p) => `
    <button class="list-item ${p.id === P.current ? 'active' : ''}" data-id="${esc(p.id)}">
      <span class="li-title">${esc(p.name)}</span>
      <span class="li-meta">${statusPill(p.status)}<span>${p.builtin ? 'pipeline integrado' : `${(p.agents || []).length} agentes`}</span></span>
    </button>`).join('');
  $('projList').querySelectorAll('.list-item').forEach((el) => el.addEventListener('click', () => openProject(el.dataset.id)));
}

async function openProject(id) {
  P.current = id;
  try { localStorage.setItem('paradax.project', id); } catch { /* sin storage */ }
  renderProjList();
  $('projEmpty').classList.add('hidden');
  $('projBody').classList.remove('hidden');
  $('pmMessages').innerHTML = '';
  document.querySelectorAll('.proj-only').forEach((el) => el.classList.toggle('hidden', isMedia()));
  document.querySelectorAll('.media-only').forEach((el) => el.classList.toggle('hidden', !isMedia()));
  if (isMedia()) {
    P.detail = MEDIA;
    renderProjHeader(MEDIA);
  } else {
    try { renderProjDetail(await apiGet(`/api/projects/${enc(id)}`)); } catch (e) { toast(e.message, 'error'); }
  }
  const active = document.querySelector('.tabs[data-tabs="proj"] .active')?.dataset.tab || 'org';
  selectTab('proj', isMedia() && ['pm', 'team', 'sched'].includes(active) ? 'org' : active);
}

async function refreshProject() {
  if (!P.current || isMedia()) return;
  try { renderProjDetail(await apiGet(`/api/projects/${enc(P.current)}`)); } catch { /* sigue */ }
}

function renderProjHeader(p) {
  $('projName').textContent = p.name;
  $('projGoal').textContent = p.goal || '';
  $('projStatus').innerHTML = statusPill(p.status);
}

function renderProjDetail(p) {
  P.detail = p;
  renderProjHeader(p);
  const building = p.status === 'planning' || p.status === 'building';
  const bt = $('buildTeamBtn');
  bt.disabled = building;
  bt.querySelector('span').textContent = building ? 'Construyendo…' : (p.agents.length ? 'Reconstruir equipo' : 'Construir equipo');
  const ar = $('projAutoRunBtn');
  ar.innerHTML = `${icon(p.auto_run ? 'auto' : 'manual')}<span>${p.auto_run ? 'Automático' : 'Manual'}</span>`;
  ar.classList.toggle('on', !!p.auto_run);
  ar.title = p.auto_run ? 'El pipeline corre solo cuando el equipo queda listo' : 'Tú decides cuándo ejecutar';
  const tab = document.querySelector('.tabs[data-tabs="proj"] .active')?.dataset.tab;
  if (tab) TAB_HOOKS[`proj:${tab}`]?.();
}

// ── Jerarquía ───────────────────────────────────────────────
async function renderProjOrg() {
  if (!P.current) return;
  const svg = $('orgSvg');
  let org;
  try { org = await apiGet(`/api/projects/${enc(P.current)}/org`); }
  catch (e) { svg.innerHTML = ''; $('orgInputs').innerHTML = `<p class="muted">No se pudo cargar: ${esc(e.message)}</p>`; return; }
  for (const n of org.nodes) APP.agentNames.set(n.id, n.name);
  renderOrg(svg, org, { onNode: openOrgNode });
  setOrgLive(svg, PLIVE);
  if (!isMedia()) renderInputsEditor(org); else $('orgInputs').innerHTML = '';
}

function openOrgNode(n) {
  if (n.kind === 'team' && !isMedia()) { openAgentCard(n.id, () => { renderProjOrg(); refreshProject(); }); return; }
  if (n.contactable) openAgentChat(n.id, n.name, n.role);
  else toast(`${n.name} es interno: trabaja sin chat directo`);
}

async function renderInputsEditor(org) {
  const box = $('orgInputs');
  const missing = [...new Set(org.nodes.filter((n) => n.kind === 'team').flatMap((n) => n.missing || []))];
  const cur = (P.detail && P.detail.inputs) || {};
  if (!org.nodes.some((n) => n.kind === 'team')) { box.innerHTML = ''; return; }
  if (!missing.length) {
    box.innerHTML = `<div class="callout callout-ok">${icon('check')}<span>Todas las entradas están resueltas: el equipo puede ejecutarse.</span></div>`;
    return;
  }
  box.innerHTML = `
    <div class="callout callout-warn">${icon('info')}<span>Faltan datos de entrada que ningún agente produce. Complétalos para desbloquear el pipeline.</span></div>
    <div class="form-grid">${missing.map((k) => `<label class="field"><span>${esc(k)}</span><input data-inkey="${esc(k)}" value="${esc(cur[k] ?? '')}"></label>`).join('')}</div>
    <button class="btn btn-primary btn-sm" id="saveInputsBtn">${icon('check')}<span>Guardar entradas</span></button>`;
  $('saveInputsBtn').addEventListener('click', async () => {
    const inputs = { ...cur };
    box.querySelectorAll('[data-inkey]').forEach((i) => { if (i.value !== '') inputs[i.dataset.inkey] = i.value; });
    try { await apiPost(`/api/projects/${enc(P.current)}/inputs`, { inputs }); } catch (e) { toast(e.message, 'error'); return; }
    toast('Entradas guardadas');
    await refreshProject(); renderProjOrg();
  });
}

// ── Project Manager ────────────────────────────────────────
async function pmSend() {
  const input = $('pmInput');
  const text = input.value.trim();
  if (!text || !P.current || P.sending) return;
  input.value = ''; autoResize(input);
  const box = $('pmMessages');
  box.querySelector('.empty-inline')?.remove();
  chatBubble(box, 'user', text, nowHM());
  const bubble = chatBubble(box, 'agent', '');
  bubble.classList.add('pending');
  P.sending = true;
  try {
    await streamSSE(`/api/projects/${enc(P.current)}/chat`, { message: text, model: APP.model }, (c) => {
      bubble.textContent += c; box.scrollTop = box.scrollHeight;
    });
  } catch (e) { bubble.textContent = `No respondió: ${e.message}`; bubble.classList.add('error'); }
  bubble.classList.remove('pending');
  P.sending = false;
  refreshProject();
}

// ── Equipo ─────────────────────────────────────────────────
async function renderProjTeam() {
  const p = P.detail;
  if (!p || isMedia()) return;
  const box = $('teamList');
  if (!p.agents.length) {
    box.innerHTML = '<div class="empty-state"><p>Este proyecto aún no tiene equipo.</p><p class="muted">Pulsa «Construir equipo» o añade un agente que ya exista.</p></div>';
    return;
  }
  box.innerHTML = p.agents.map((a) => `
    <div class="row-card" data-id="${esc(a)}">
      <div class="rc-main"><b>${esc(agentName(a))}</b><code>${esc(a)}</code></div>
      <div class="rc-side">
        <span class="spec muted" data-spec="${esc(a)}">…</span>
        <button class="btn btn-ghost btn-sm" data-card="${esc(a)}">${icon('info')}<span>Ficha</span></button>
        <button class="btn btn-ghost btn-sm" data-rm="${esc(a)}" aria-label="Quitar ${esc(a)} del proyecto">${icon('close')}</button>
      </div>
    </div>`).join('');
  box.querySelectorAll('[data-card]').forEach((b) => b.addEventListener('click', () => openAgentCard(b.dataset.card, refreshProject)));
  box.querySelectorAll('[data-rm]').forEach((b) => b.addEventListener('click', () => removeAgentFromProject(b.dataset.rm)));
  for (const a of p.agents) loadSpecialization(a);
}

async function loadSpecialization(aid) {
  const el = document.querySelector(`#teamList [data-spec="${CSS.escape(aid)}"]`);
  if (!el) return;
  try {
    const st = await apiGet(`/api/factory/agents/${enc(aid)}/specialize`);
    if (st.is_specialist) {
      el.innerHTML = `${icon('star')}<span>modelo propio</span>`; el.title = st.current_model; el.className = 'spec spec-done';
      return;
    }
    el.innerHTML = `<button class="btn btn-ghost btn-sm ${st.ready ? 'ready' : ''}">${icon('graduate')}<span>${st.examples}/${st.min_examples} ejemplos</span></button>`;
    el.className = 'spec';
    el.querySelector('button').addEventListener('click', () => specializeAgent(aid, st));
  } catch { el.textContent = ''; }
}

async function specializeAgent(aid, st) {
  const force = !st.ready;
  const msg = force
    ? `${aid} solo tiene ${st.examples} de ${st.min_examples} ejemplos verificados.\n\n¿Forzar una prueba de entrenamiento? Con tan pocos ejemplos memoriza en vez de aprender: solo sirve para validar el circuito.\n\nTarda minutos y descarga los modelos de Ollama mientras dura.`
    : `Entrenar el modelo propio de ${aid} con ${st.examples} ejemplos verificados.\n\nTarda minutos y descarga los modelos de Ollama mientras dura. Al terminar se promociona.`;
  if (!confirm(msg)) return;
  toast(`Entrenando ${aid}…`);
  try {
    const r = await apiPost(`/api/factory/agents/${enc(aid)}/specialize`, { version: 'v1', force, promote: true });
    if (r.ok) toast(`${aid} ya tiene modelo propio: ${r.published}`, 'ok');
    else toast(`No se entrenó: ${r.detail || r.error || 'error desconocido'}`, 'error');
  } catch (e) { toast(`Error al entrenar: ${e.message}`, 'error'); }
  renderProjTeam();
}

async function openAgentPicker() {
  let specs = [];
  try { specs = (await apiGet('/api/factory/specs')).specs || []; } catch { /* vacío */ }
  const inProj = new Set(P.detail?.agents || []);
  const avail = specs.filter((s) => !inProj.has(s.id));
  $('pickerSel').innerHTML = avail.length
    ? avail.map((s) => `<option value="${esc(s.id)}">${esc(s.name)}${s.project ? ' · ' + esc(s.project) : ''}</option>`).join('')
    : '<option value="">No hay agentes libres: créalos en Constructor</option>';
  $('picker').classList.remove('hidden');
}

async function addAgentToProject() {
  const id = $('pickerSel').value;
  if (!id || !P.current) return;
  await apiPost(`/api/projects/${enc(P.current)}/agents`, { agent_id: id });
  $('picker').classList.add('hidden');
  await refreshProject();
}

async function removeAgentFromProject(id) {
  if (!confirm(`¿Quitar «${id}» de este proyecto? El agente sigue existiendo.`)) return;
  await apiDel(`/api/projects/${enc(P.current)}/agents/${enc(id)}`);
  await refreshProject();
}

// ── Ejecuciones ────────────────────────────────────────────
async function renderProjRuns() {
  if (isMedia()) { renderMediaRuns(); return; }
  const p = P.detail;
  if (!p) return;
  const tasks = (p.tasks || []).slice(-10).reverse();
  $('taskList').innerHTML = tasks.length ? tasks.map((t) => `
    <div class="row-card">
      <div class="rc-main"><span>${esc(trunc(t.request || '', 140))}</span>${t.run_id ? `<code>${esc(t.run_id)}</code>` : ''}</div>
      <div class="rc-side">${statusPill(t.status)}<span class="muted">${esc(fmtDate(t.updated_at || t.created_at))}</span></div>
    </div>`).join('') : '<p class="muted">Sin tareas todavía. Pídeselas al Project Manager o pulsa Ejecutar.</p>';
  $('projLog').innerHTML = (p.log || []).slice(-60).reverse().map((l) => `<li>${esc(l)}</li>`).join('') || '<li class="muted">Bitácora vacía</li>';
  let results = [];
  try { results = (await apiGet(`/api/projects/${enc(p.id)}/results`)).results || []; } catch { /* sin resultados */ }
  $('resultList').innerHTML = results.length ? results.slice(0, 6).map((r) => `
    <button class="row-card row-btn" data-run="${esc(r.name)}" title="Abrir en Finder">
      <div class="rc-main">${icon('folder')}<b>${esc(r.name)}</b></div>
      <div class="rc-side muted">${r.files.length} archivo(s)</div>
    </button>`).join('') : '<p class="muted">Sin resultados: ejecuta el proyecto y sus archivos aparecerán aquí.</p>';
  $('resultList').querySelectorAll('[data-run]').forEach((el) => el.addEventListener('click',
    () => apiPost(`/api/projects/${enc(p.id)}/results/open?run=${enc(el.dataset.run)}`).catch((e) => toast(e.message, 'error'))));
}

async function renderMediaRuns() {
  let runs = [];
  try { runs = (await apiGet('/api/runs?limit=12')).runs || []; } catch { /* sin runs */ }
  $('mediaRuns').innerHTML = runs.length ? runs.map((r) => `
    <div class="row-card">
      <div class="rc-main"><span>${esc(trunc(r.request || r.id, 120))}</span><code>${esc(r.id)}</code></div>
      <div class="rc-side">${statusPill(r.status)}<span class="muted">${esc(fmtDate(r.updated_at || r.created_at))}</span></div>
    </div>`).join('') : '<p class="muted">Sin runs registrados.</p>';
}

async function launchMedia() {
  const input = $('mediaInput');
  const request = input.value.trim();
  if (!request) return;
  try {
    await apiPost('/api/agents/media-manager/launch', { request, make_reel: $('mediaReel').checked });
    input.value = '';
    toast('Run lanzado: síguelo en la jerarquía o en Actividad');
    selectTab('proj', 'org');
  } catch (e) { toast(e.message, 'error'); }
}

// ── Programación ───────────────────────────────────────────
function buildDayGrid(grid, days) {
  if (grid.childElementCount) return;
  for (let d = 1; d <= 31; d++) {
    const b = document.createElement('button');
    b.className = 'day'; b.textContent = d; b.type = 'button';
    b.addEventListener('click', () => { days.has(d) ? days.delete(d) : days.add(d); b.classList.toggle('sel'); });
    grid.appendChild(b);
  }
}

function scheduleRow(s, projectName = '') {
  const runs = s._summary?.runs || 0;
  const est = s._estimated_minutes != null ? `unos ${s._estimated_minutes} min${runs ? ` (según ${runs} runs)` : ' (estimación inicial)'}` : '';
  return `
    <div class="row-card ${s.enabled ? '' : 'off'}">
      <div class="rc-main">
        ${projectName ? `<b>${esc(projectName)}</b>` : ''}
        <span>${icon('calendar')} días ${esc(s.days_of_month.join(', '))} · ${icon('flag')} termina antes de las ${esc(s.deadline_time)}</span>
        <span class="muted">${s._start_time ? `arranca hacia las ${esc(s._start_time)}` : ''}${s._start_time && est ? ' · ' : ''}${est}</span>
      </div>
      <div class="rc-side">
        <button class="btn btn-ghost btn-sm" data-tog="${esc(s.id)}" data-en="${s.enabled ? 0 : 1}">${s.enabled ? 'Pausar' : 'Activar'}</button>
        <button class="btn btn-ghost btn-sm" data-del="${esc(s.id)}" aria-label="Borrar programación">${icon('trash')}</button>
      </div>
    </div>`;
}

function wireScheduleRows(box, reload) {
  box.querySelectorAll('[data-tog]').forEach((b) => b.addEventListener('click', async () => {
    await apiPost(`/api/automation/schedules/${enc(b.dataset.tog)}/toggle`, { enabled: b.dataset.en === '1' }); reload();
  }));
  box.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', async () => {
    if (!confirm('¿Borrar esta programación?')) return;
    await apiDel(`/api/automation/schedules/${enc(b.dataset.del)}`); reload();
  }));
}

async function renderProjSched() {
  if (!P.current || isMedia()) return;
  buildDayGrid($('schedDays'), P.schedDays);
  let all = [];
  try { all = (await apiGet('/api/automation/schedules')).schedules || []; } catch { /* vacío */ }
  const mine = all.filter((s) => s.project_id === P.current);
  const box = $('schedList');
  box.innerHTML = mine.length ? mine.map((s) => scheduleRow(s)).join('') : '<p class="muted">Sin programaciones para este proyecto.</p>';
  wireScheduleRows(box, renderProjSched);
}

async function addProjSchedule() {
  const days = [...P.schedDays], time = $('schedTime').value;
  if (!days.length || !time) { toast('Elige al menos un día y la hora límite', 'error'); return; }
  try {
    await apiPost('/api/automation/schedules', { project_id: P.current, deadline_time: time, days_of_month: days, label: '' });
    P.schedDays.clear();
    $('schedDays').querySelectorAll('.sel').forEach((c) => c.classList.remove('sel'));
    toast('Programado'); renderProjSched();
  } catch (e) { toast(e.message, 'error'); }
}

// ── Acciones del proyecto ──────────────────────────────────
async function runProject() {
  if (isMedia()) { selectTab('proj', 'runs'); $('mediaInput').focus(); return; }
  try {
    await apiPost(`/api/projects/${enc(P.current)}/run`);
    toast('Ejecución lanzada: la jerarquía muestra quién trabaja');
    selectTab('proj', 'org');
  } catch (e) { toast(e.message, 'error'); }
}

async function buildTeam() {
  await apiPost(`/api/projects/${enc(P.current)}/build`);
  toast('El Project Manager está construyendo el equipo');
  clearInterval(P.polling);
  P.polling = setInterval(async () => {
    try {
      const p = await apiGet(`/api/projects/${enc(P.current)}`);
      renderProjDetail(p);
      if (p.status === 'ready' || p.status === 'failed') {
        clearInterval(P.polling); P.polling = null;
        loadProjects();
        toast(p.status === 'ready' ? 'Equipo listo' : 'La construcción falló: mira la bitácora', p.status === 'ready' ? 'ok' : 'error');
      }
    } catch { /* sigue */ }
  }, 2000);
}

async function toggleAutoRun() {
  if (!P.detail || isMedia()) return;
  await apiPost(`/api/projects/${enc(P.current)}/auto-run`, { enabled: !P.detail.auto_run });
  refreshProject();
}

async function undoLastRun() {
  if (!confirm('¿Deshacer el último run? Los archivos vuelven al estado anterior a ese run.')) return;
  try {
    const r = await apiPost(`/api/projects/${enc(P.current)}/undo`);
    toast(r.ok ? 'Revertido al estado anterior' : `No se pudo deshacer: ${r.error || ''}`, r.ok ? 'ok' : 'error');
  } catch (e) { toast(e.message, 'error'); }
}

async function deleteProject() {
  if (!confirm(`¿Eliminar el proyecto «${P.detail?.name}» y sus agentes?`)) return;
  await apiDel(`/api/projects/${enc(P.current)}`);
  P.current = null;
  try { localStorage.removeItem('paradax.project'); } catch { /* sin storage */ }
  $('projBody').classList.add('hidden'); $('projEmpty').classList.remove('hidden');
  loadProjects();
}

async function createProject() {
  const name = $('npName').value.trim(), goal = $('npGoal').value.trim();
  if (name.length < 2) { toast('Pon un nombre de al menos 2 letras', 'error'); return; }
  const p = await apiPost('/api/projects', { name, goal });
  $('projectOverlay').classList.add('hidden');
  await loadProjects();
  openProject(p.id);
}

// ── En vivo ────────────────────────────────────────────────
function projLiveEvent(ev) {
  const mine = ev.project === P.current || (isMedia() && (ev.kind === 'run_started' || ev.kind === 'run_finished' || !ev.project));
  if (ev.kind === 'project_run_started' || ev.kind === 'run_started') {
    if (!mine) return;
    PLIVE.runId = ev.run_id || null;
    PLIVE.active.clear(); PLIVE.done.clear(); PLIVE.failed.clear();
  } else if (ev.kind === 'agent_started' && (!PLIVE.runId || ev.run_id === PLIVE.runId)) {
    PLIVE.active.add(ev.agent); PLIVE.done.delete(ev.agent);
  } else if (ev.kind === 'agent_completed' && (!PLIVE.runId || ev.run_id === PLIVE.runId)) {
    PLIVE.active.delete(ev.agent); PLIVE.done.add(ev.agent);
  } else if (ev.kind === 'agent_failed' && (!PLIVE.runId || ev.run_id === PLIVE.runId)) {
    PLIVE.active.delete(ev.agent); PLIVE.failed.add(ev.agent);
  } else if (ev.kind === 'project_run_finished' || ev.kind === 'run_finished') {
    PLIVE.active.clear();
    if (mine) setTimeout(() => { refreshProject(); }, 400);
  } else if (ev.kind === 'dialogue' && ev.project === P.current) {
    refreshProject();
  } else return;
  setOrgLive($('orgSvg'), PLIVE);
}

function setupProjects() {
  SECTION_LOADERS.projects = loadProjects;
  TAB_HOOKS['proj:org'] = renderProjOrg;
  TAB_HOOKS['proj:team'] = renderProjTeam;
  TAB_HOOKS['proj:runs'] = renderProjRuns;
  TAB_HOOKS['proj:sched'] = renderProjSched;
  TAB_HOOKS['proj:pm'] = () => {
    const box = $('pmMessages');
    if (!box.childElementCount) box.innerHTML = '<div class="empty-inline">Cuéntale al Project Manager qué necesitas. Si le pides una tarea («haz…», «genera…»), la lanza con el equipo.</div>';
    $('pmInput').focus();
  };
  $('newProjectBtn').addEventListener('click', () => { $('npName').value = ''; $('npGoal').value = ''; $('projectOverlay').classList.remove('hidden'); $('npName').focus(); });
  $('npCancel').addEventListener('click', () => $('projectOverlay').classList.add('hidden'));
  $('npCreate').addEventListener('click', createProject);
  $('runProjectBtn').addEventListener('click', runProject);
  $('buildTeamBtn').addEventListener('click', buildTeam);
  $('projAutoRunBtn').addEventListener('click', toggleAutoRun);
  $('projUndoBtn').addEventListener('click', undoLastRun);
  $('projDeleteBtn').addEventListener('click', deleteProject);
  $('pmSend').addEventListener('click', pmSend);
  onEnterSend($('pmInput'), pmSend);
  $('addAgentBtn').addEventListener('click', openAgentPicker);
  $('pickerAdd').addEventListener('click', addAgentToProject);
  $('pickerCancel').addEventListener('click', () => $('picker').classList.add('hidden'));
  $('openResultsBtn').addEventListener('click', () => apiPost(`/api/projects/${enc(P.current)}/results/open`).catch(() => toast('Aún no hay resultados: ejecuta el proyecto primero', 'error')));
  $('addSchedBtn').addEventListener('click', addProjSchedule);
  $('mediaLaunch').addEventListener('click', launchMedia);
  $('mediaInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') launchMedia(); });
}
