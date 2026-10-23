/* Área Entrenamiento: qué modelo usa cada agente, cómo van los alumnos y la
   cola del Entrenador. Lo vetado se estudia en el Laboratorio. */

async function loadTraining() {
  const tab = document.querySelector('.tabs[data-tabs="train"] .active')?.dataset.tab || 'students';
  selectTab('train', tab);
}

const LEVEL_LABEL = { ok: 'aprendiendo', alerta: 'atención', cuarentena: 'en cuarentena', nada: 'sin alumno' };

async function renderStudents() {
  let status = {}, agents = [], lab = { models: [] };
  try { status = await apiGet('/api/training/status'); } catch { /* sin estado */ }
  try { agents = (await apiGet('/api/agents?project=all')).agents || []; } catch { /* sin agentes */ }
  try { lab = await apiGet('/api/lab/overview'); } catch { /* sin laboratorio */ }
  const vetoedBy = new Map();
  for (const m of lab.models.filter((x) => x.vetoed)) {
    if (!vetoedBy.has(m.agent)) vetoedBy.set(m.agent, []);
    vetoedBy.get(m.agent).push(m.version);
  }
  const sys = Object.entries(status).map(([id, st]) => ({ id, name: agentName(id), area: 'Sistema', text: plain(st.text), level: st.level }));
  const used = agents.filter((a) => a.active_model).map((a) => ({
    id: a.id, name: a.name, area: a.constructed ? 'Construido' : 'Media Manager',
    text: a.specialized ? `modelo propio en producción: ${a.active_model}` : `en producción: ${a.active_model}`,
    level: a.specialized ? 'ok' : 'nada', model: a.active_model, specialized: a.specialized,
  }));
  for (const a of agents) APP.agentNames.set(a.id, a.name);
  const rows = [...sys, ...used];
  $('studentRows').innerHTML = rows.map((r) => {
    const q = vetoedBy.get(r.id);
    return `
    <tr>
      <td><b>${esc(r.name)}</b><br><code>${esc(r.id)}</code></td>
      <td>${esc(r.area)}</td>
      <td><span class="lvl lvl-${esc(r.level)}">${esc(LEVEL_LABEL[r.level] || r.level)}</span>${r.specialized ? ` <span class="tag tag-student">${icon('star')}propio</span>` : ''}</td>
      <td class="muted">${esc(r.text)}</td>
      <td>${q ? `<button class="btn btn-ghost btn-sm danger" data-lab="1">${icon('hazard')}<span>${q.length} en cuarentena</span></button>` : ''}</td>
    </tr>`;
  }).join('');
  $('studentRows').querySelectorAll('[data-lab]').forEach((b) => b.addEventListener('click', () => showSection('lab')));
}

async function renderTrainer() {
  let q = [];
  try { q = (await apiGet('/api/factory/entrenador/queue')).queue || []; } catch { /* vacía */ }
  $('trainQueue').innerHTML = q.length ? q.map((b) => `
    <div class="row-card">
      <div class="rc-main">
        <b>${esc(b.agent_name || b.agent_id)}</b>
        <span class="muted">foco: ${esc(b.focus || '—')}${b.material ? ` · material: ${esc(b.material.kind)} (${b.material.chars} caracteres)` : ''}</span>
        ${b.dataset ? `<span class="muted">${b.dataset.ejemplos_verificados} ejemplos verificados</span>` : ''}
      </div>
      <div class="rc-side">
        ${statusPill(b.status === 'dataset-listo' ? 'ready' : 'pending')}
        <button class="btn btn-primary btn-sm" data-run="${esc(b.agent_id)}">${icon('graduate')}<span>Destilar</span></button>
        <button class="btn btn-ghost btn-sm" data-del="${esc(b.agent_id)}">Quitar</button>
      </div>
    </div>`).join('') : '<p class="muted">La cola está vacía. Envía agentes desde su ficha («Entrenar»).</p>';
  $('trainQueue').querySelectorAll('[data-run]').forEach((b) => b.addEventListener('click', async () => {
    b.disabled = true; b.querySelector('span').textContent = 'Destilando…';
    try { await apiPost(`/api/factory/entrenador/queue/${enc(b.dataset.run)}/run`); toast('Destilación terminada', 'ok'); }
    catch (e) { toast(e.message, 'error'); }
    renderTrainer();
  }));
  $('trainQueue').querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', async () => {
    await apiDel(`/api/factory/entrenador/queue/${enc(b.dataset.del)}`); renderTrainer();
  }));
}

async function ingestMaterial() {
  const source = $('matInput').value.trim();
  if (!source) return;
  const out = $('matOut');
  out.textContent = 'El Entrenador despierta a un lector…';
  try {
    const m = await apiPost('/api/factory/entrenador/ingest', { source });
    out.textContent = `Leído (${m.kind}, ${m.chars} caracteres): ${trunc(m.text, 160)}`;
  } catch (e) { out.textContent = `No se pudo leer: ${e.message}`; }
}

function bar(value, max) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return `<span class="bar"><span style="width:${pct}%"></span></span>`;
}

async function renderExams() {
  let data = { exams: [], review_from: 54 };
  try { data = await apiGet('/api/training/exam'); } catch { /* sin exámenes */ }
  $('examFrom').textContent = data.review_from;
  $('examList').innerHTML = data.exams.length ? data.exams.map((e) => {
    const c = e.criteria || {};
    const rv = e.review || {};
    const reviewLine = rv.error ? `<span class="danger">Revisión con Claude no disponible: ${esc(rv.error)}</span>`
      : rv.ran ? `Revisados por Claude: ${rv.reviewed} · nota media con revisión ${e.mean_total_reviewed ?? '—'}/100 · ${rv.improved_examples} correcciones del alumno al dataset`
      : e.auto_mean >= e.review_from ? 'Nivel suficiente para la revisión con Claude, pero en este examen estaba desactivada'
      : `Aún no llega a ${e.review_from} de media: sin revisión de Claude`;
    return `
      <article class="exam">
        <header><b>${esc(e.model)}</b><span class="muted">${esc(fmtDate(e.ts))} · ${e.cases} casos</span></header>
        <div class="exam-score"><span class="big-num">${e.auto_mean}</span><span class="muted">/ 60 automático</span>${bar(e.auto_mean, 60)}</div>
        <div class="exam-criteria">${['valido', 'prompt', 'evals', 'ajuste'].map((k) => `<span><b>${k}</b> ${c[k] ?? '—'}/15 ${bar(c[k] || 0, 15)}</span>`).join('')}</div>
        <p class="small">${reviewLine}</p>
        <details><summary>Casos</summary>${(e.results || []).map((r) => `
          <div class="exam-case"><b>${r.total}/100</b> ${esc(trunc(r.goal, 110))}
            ${r.auto.notes.length ? `<div class="muted small">${esc(r.auto.notes.join(' · '))}</div>` : ''}
            ${r.review ? `<div class="small">Claude: ${r.review.score}/40 · ${r.review.usable ? 'sirve' : 'no sirve aún'} — ${esc(r.review.fix)}</div>` : ''}
          </div>`).join('')}</details>
      </article>`;
  }).join('') : '<p class="muted">Aún no hay exámenes. Se hacen cada noche tras entrenar, o a mano: python -m agent_os.training.graded_exam --model …</p>';
}

function setupTraining() {
  TAB_HOOKS['train:exam'] = renderExams;
  SECTION_LOADERS.training = loadTraining;
  TAB_HOOKS['train:students'] = renderStudents;
  TAB_HOOKS['train:trainer'] = renderTrainer;
  $('matGo').addEventListener('click', ingestMaterial);
  $('matInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') ingestMaterial(); });
  $('trainerChat').addEventListener('click', () => openAgentChat('entrenador', 'Entrenador', 'Destila alumnos especializados'));
}
