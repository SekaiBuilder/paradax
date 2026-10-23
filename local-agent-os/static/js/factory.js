/* Área Constructor (fábrica): el Team Constructor, los agentes que ha
   construido, la librería de skills y las peticiones del agente fantasma. */

const F = { specs: [], projects: new Map() };

// Textos del backend que aún traen emojis: se muestran limpios.
const plain = (s) => String(s ?? '').replace(/\p{Extended_Pictographic}️?/gu, '').replace(/\s{2,}/g, ' ').trim();

async function loadFactory() {
  const tab = document.querySelector('.tabs[data-tabs="fab"] .active')?.dataset.tab || 'team';
  selectTab('fab', tab);
}

// ── Equipo constructor ─────────────────────────────────────
const FAB_LEVELS = [
  { id: 'direccion', label: 'Dirección', description: 'Recibe tu petición y dirige' },
  { id: 'constructor', label: 'Diseño y fabricación', description: 'Planifica, define skills y construye' },
  { id: 'control', label: 'Control de calidad', description: 'Revisa y valida cada agente' },
  { id: 'ejecucion', label: 'Ejecución y mejora', description: 'Lanza el equipo y lo entrena' },
  { id: 'apoyo', label: 'Apoyo bajo demanda', description: 'Despiertan solo cuando hacen falta' },
];
const FAB_LEVEL_OF = {
  project_manager: 'direccion',
  team_planner: 'constructor', skills_definer: 'constructor', skill_master: 'constructor', constructor: 'constructor',
  auditor: 'control', validador: 'control',
  orquestador: 'ejecucion', entrenador: 'ejecucion',
  ghost: 'apoyo', doc_reader: 'apoyo', url_reader: 'apoyo',
};

async function renderFabTeam() {
  let graph, status = {};
  try { graph = await apiGet('/api/system/agents'); } catch (e) { toast(e.message, 'error'); return; }
  try { status = await apiGet('/api/training/status'); } catch { /* sin estado */ }
  const nodes = graph.agents.filter((a) => a.group === 'constructor').map((a) => {
    APP.agentNames.set(a.id, a.name);
    return {
      id: a.id, name: a.name, role: `${a.description}\n\n${plain(status[a.id]?.text || '')}`, level: FAB_LEVEL_OF[a.id] || 'apoyo',
      kind: 'system', contactable: a.contactable, model: a.contactable ? (a.on_demand ? 'bajo demanda' : 'chat disponible') : (a.on_demand ? 'bajo demanda' : 'interno'),
      quarantined: [],
    };
  });
  const ids = new Set(nodes.map((n) => n.id));
  const edges = graph.edges.filter((e) => ids.has(e.from) && ids.has(e.to)).map((e) => ({ ...e, kind: 'mando' }));
  renderOrg($('fabSvg'), { levels: FAB_LEVELS, nodes, edges }, {
    onNode: (n) => (n.contactable ? openAgentChat(n.id, n.name, n.role.split('\n')[0]) : toast(`${n.name} trabaja internamente: no tiene chat`)),
  });
}

// ── Agentes construidos ────────────────────────────────────
async function renderFabAgents() {
  try { F.specs = (await apiGet('/api/factory/specs')).specs || []; } catch { F.specs = []; }
  try {
    const ps = (await apiGet('/api/projects')).projects || [];
    F.projects = new Map(ps.map((p) => [p.id, p.name]));
  } catch { /* sin proyectos */ }
  const groups = new Map();
  for (const s of F.specs) {
    APP.agentNames.set(s.id, s.name);
    const key = s.project || '';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(s);
  }
  const order = [...groups.keys()].sort((a, b) => (a === '') - (b === '') || a.localeCompare(b));
  $('fabAgents').innerHTML = F.specs.length ? order.map((key) => `
    <section class="group">
      <h3>${key ? esc(F.projects.get(key) || key) : 'Sin proyecto'} <span class="muted">${groups.get(key).length}</span></h3>
      <div class="cards">
        ${groups.get(key).map((s) => `
          <button class="agent-card" data-id="${esc(s.id)}">
            <span class="ac-head"><b>${esc(s.name)}</b><span class="tag tag-${esc(s.tier || (s.uses_tools ? 'secondary' : 'tertiary'))}">${(s.tier || (s.uses_tools ? 'secondary' : 'tertiary')) === 'secondary' ? 'Decide' : 'Ejecuta'}</span></span>
            <span class="ac-desc">${esc(trunc(s.description || '', 120))}</span>
            <span class="ac-foot"><code>${esc(s.writes)}</code><span class="muted">${(s.skills || []).length} skills · ${(s.tools || []).length} tools</span></span>
          </button>`).join('')}
      </div>
    </section>`).join('') : '<div class="empty-state"><p>Aún no hay agentes construidos.</p><p class="muted">Pulsa «Construir agente» y describe lo que necesitas.</p></div>';
  $('fabAgents').querySelectorAll('.agent-card').forEach((el) => el.addEventListener('click', () => openAgentCard(el.dataset.id, renderFabAgents)));
}

// ── Skills ─────────────────────────────────────────────────
async function renderFabSkills() {
  let data;
  try { data = await apiGet('/api/factory/skills'); } catch (e) { toast(e.message, 'error'); return; }
  $('fabSkills').innerHTML = (data.skills || []).map((s) => `
    <div class="row-card">
      <div class="rc-main"><b>${esc(s.name)}</b><span class="muted">${esc(s.description || '')}</span></div>
      <div class="rc-side"><code>${esc(s.id)}</code>${(s.tags || []).slice(0, 3).map((t) => `<span class="chip">${esc(t)}</span>`).join('')}</div>
    </div>`).join('') || '<p class="muted">La librería está vacía.</p>';
}

// ── Peticiones del fantasma ────────────────────────────────
async function renderFabGhost() {
  let skills = [], tools = [];
  try { skills = (await apiGet('/api/factory/ghost/pending')).pending || []; } catch { /* vacío */ }
  try { tools = (await apiGet('/api/factory/ghost/pending_tools')).pending_tools || []; } catch { /* vacío */ }
  const row = (p, kind) => `
    <div class="row-card">
      <div class="rc-main"><b>${esc(p.name || p.id)}</b><span class="muted">${esc(trunc(p.description || p.reason || '', 200))}</span><code>${esc(p.id)}</code></div>
      <div class="rc-side">
        <button class="btn btn-primary btn-sm" data-approve="${esc(p.id)}" data-kind="${kind}">${icon('check')}<span>Aprobar</span></button>
        ${kind === 'skill' ? `<button class="btn btn-ghost btn-sm" data-reject="${esc(p.id)}">Rechazar</button>` : ''}
      </div>
    </div>`;
  $('fabGhost').innerHTML = (skills.length || tools.length)
    ? (skills.length ? `<h3>Skills propuestas</h3>${skills.map((p) => row(p, 'skill')).join('')}` : '')
      + (tools.length ? `<h3>Herramientas propuestas</h3>${tools.map((p) => row(p, 'tool')).join('')}` : '')
    : '<div class="empty-state"><p>No hay peticiones pendientes.</p><p class="muted">Cuando el Validador falla y escalas al fantasma, sus propuestas esperan aquí tu aprobación. Nada se aplica solo.</p></div>';
  $('fabGhost').querySelectorAll('[data-approve]').forEach((b) => b.addEventListener('click', async () => {
    const path = b.dataset.kind === 'tool' ? '/api/factory/ghost/approve_tool' : '/api/factory/ghost/approve';
    try { await apiPost(path, { id: b.dataset.approve }); toast('Aprobado', 'ok'); } catch (e) { toast(e.message, 'error'); }
    renderFabGhost();
  }));
  $('fabGhost').querySelectorAll('[data-reject]').forEach((b) => b.addEventListener('click', async () => {
    await apiPost('/api/factory/ghost/reject', { id: b.dataset.reject }); renderFabGhost();
  }));
  const n = skills.length + tools.length;
  $('ghostCount').textContent = n ? String(n) : '';
}

// ── Construir agente ───────────────────────────────────────
function openBuild() {
  $('buildResult').classList.add('hidden');
  $('buildInput').value = '';
  $('buildOverlay').classList.remove('hidden');
  $('buildInput').focus();
}

async function runBuild() {
  const request = $('buildInput').value.trim();
  if (request.length < 5) { toast('Describe un poco más lo que debe hacer', 'error'); return; }
  const out = $('buildResult'), go = $('buildGo');
  go.disabled = true; go.querySelector('span').textContent = 'Construyendo…';
  out.classList.remove('hidden');
  out.innerHTML = '<span class="muted">El Constructor está componiendo el agente con skills y tools existentes…</span>';
  try {
    const r = await apiPost('/api/factory/build', { request, model: APP.model, escalate: $('buildEscalate').checked });
    if (r.ok && r.registered) {
      out.innerHTML = `<b>Agente construido: ${esc(r.spec.name)}</b> <code>${esc(r.spec.id)}</code><br><span class="muted">lee ${esc((r.spec.reads || []).join(', ') || '—')} · escribe ${esc(r.spec.writes)}</span>`;
      if (APP.section === 'factory') renderFabAgents();
    } else if (r.proposal) {
      out.innerHTML = `<b>El Validador lo rechazó</b> (${esc(r.error)}). El fantasma dejó una propuesta <code>${esc(r.proposal.id)}</code> en Peticiones: necesita tu aprobación.`;
    } else {
      out.innerHTML = `<b>No se pudo construir:</b> ${esc(r.error || 'motivo desconocido')}`;
    }
  } catch (e) {
    out.innerHTML = `<b>Error:</b> ${esc(e.message)}`;
  } finally {
    go.disabled = false; go.querySelector('span').textContent = 'Construir';
  }
}

function setupFactory() {
  SECTION_LOADERS.factory = loadFactory;
  TAB_HOOKS['fab:team'] = renderFabTeam;
  TAB_HOOKS['fab:agents'] = renderFabAgents;
  TAB_HOOKS['fab:skills'] = renderFabSkills;
  TAB_HOOKS['fab:ghost'] = renderFabGhost;
  $('buildBtn').addEventListener('click', openBuild);
  $('buildCancel').addEventListener('click', () => $('buildOverlay').classList.add('hidden'));
  $('buildGo').addEventListener('click', runBuild);
}
