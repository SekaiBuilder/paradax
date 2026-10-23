/* Área Laboratorio: zona de cuarentena, entrevistas con memoria y archivo.
   Solo aparecen modelos vetados o con casos de cuarentena. */

const LAB = { models: [], model: null, session: null, sending: false, doc: null };

async function loadLab() {
  try {
    const data = await apiGet('/api/lab/overview');
    LAB.models = data.models || [];
    $('labCount').textContent = LAB.models.filter((m) => m.vetoed).length || '';
  } catch (e) { toast(e.message, 'error'); }
  const tab = document.querySelector('.tabs[data-tabs="lab"] .active')?.dataset.tab || 'quarantine';
  selectTab('lab', tab);
}

function labModelList(boxId, onPick, keep = () => true) {
  const box = $(boxId);
  const models = LAB.models.filter(keep);
  box.innerHTML = models.length ? models.map((m) => `
    <button class="list-item ${m.model === LAB.model ? 'active' : ''}" data-model="${esc(m.model)}">
      <span class="li-title">${m.deleted ? icon('trash', 'muted') : m.vetoed ? icon('hazard', 'danger') : icon('release', 'muted')}${esc(m.agent)}</span>
      <span class="version ${m.deleted ? 'gone' : ''}">versión ${esc(m.version)}</span>
      <span class="li-meta"><span>${m.cases} casos</span><span>${m.sessions ? `${m.sessions} entrevistas` : 'sin entrevistas'}</span>${m.deleted ? '<span>eliminado</span>' : m.vetoed ? '' : '<span>liberado</span>'}</span>
    </button>`).join('') : '<div class="empty-state"><p>La cuarentena está vacía.</p><p class="muted">Cuando el detector nocturno marque a un alumno, aparecerá aquí.</p></div>';
  box.querySelectorAll('[data-model]').forEach((el) => el.addEventListener('click', () => onPick(el.dataset.model)));
}

// ── Cuarentena ─────────────────────────────────────────────
function renderQuarantine() {
  labModelList('qModels', pickQuarantineModel);
  if (LAB.model) pickQuarantineModel(LAB.model);
  else if (LAB.models.length) pickQuarantineModel(LAB.models[0].model);
}

async function pickQuarantineModel(model) {
  LAB.model = model;
  document.querySelectorAll('#qModels .list-item').forEach((el) => el.classList.toggle('active', el.dataset.model === model));
  const m = LAB.models.find((x) => x.model === model);
  if (!m) return;
  $('qDetail').innerHTML = `
    <header class="q-head">
      <div>
        <h2>${esc(m.agent)}</h2>
        <p class="version big ${m.deleted ? 'gone' : ''}">versión ${esc(m.version)}</p>
        <p class="muted"><code>${esc(m.model)}</code></p>
      </div>
      <div class="q-actions">
        ${m.deleted ? '' : `<button class="btn btn-primary" id="qInterview">${icon('chat')}<span>Entrevistar</span></button>`}
        ${m.vetoed ? `<button class="btn btn-ghost" id="qRelease">${icon('release')}<span>Quitar veto</span></button>` : ''}
        ${m.deleted ? '' : `<button class="btn btn-ghost danger" id="qDelete">${icon('trash')}<span>Eliminar</span></button>`}
      </div>
    </header>
    <div class="callout ${m.deleted ? '' : m.vetoed ? 'callout-danger' : 'callout-ok'}">${icon(m.deleted ? 'trash' : m.vetoed ? 'shield' : 'release')}
      <span><b>${m.deleted ? 'Eliminado de Ollama.' : m.vetoed ? 'Vetado en producción.' : 'Sin veto.'}</b> ${esc(m.deleted ? 'Se conservan sus casos y su memoria como prueba. Los pesos siguen en training/adapters/.' : (m.reason || 'Ya no está vetado; sigue aquí por sus casos.'))}${m.reassigned ? ` · Reasignado a: ${esc(m.reassigned)}` : ''}</span>
    </div>
    <h3>Casos</h3>
    <div id="qCases" class="stack"><p class="muted">Cargando…</p></div>
    <div id="qCase"></div>`;
  $('qInterview')?.addEventListener('click', () => { LAB.model = model; selectTab('lab', 'interview'); });
  $('qDelete')?.addEventListener('click', () => openDelete(m));
  $('qRelease')?.addEventListener('click', async () => {
    if (!confirm(`¿Quitar el veto a ${model}?\n\nNo lo pone en producción: solo entra si además está en models.json y pasa el evaluador.`)) return;
    try { await apiPost('/api/lab/release', { model }); toast('Veto retirado', 'ok'); } catch (e) { toast(e.message, 'error'); }
    loadLab();
  });
  let cases = [];
  try { cases = (await apiGet(`/api/lab/cases?model=${enc(model)}`)).cases || []; } catch { /* sin casos */ }
  $('qCases').innerHTML = cases.length ? cases.map((c) => `
    <button class="row-card row-btn" data-case="${esc(c.id)}">
      <div class="rc-main"><b>${esc(trunc(c.task, 110))}</b>
        <span class="signals">${c.signals.map((s) => `<span class="sig sig-${esc(s.severity)}">${esc(s.code)}</span>`).join('')}</span>
      </div>
      <div class="rc-side"><span class="pill pill-${esc(c.category)}">${esc(c.category_label)}</span><span class="muted">noche ${esc(c.night)}</span></div>
    </button>`).join('') : '<p class="muted">Sin casos registrados para esta versión.</p>';
  $('qCases').querySelectorAll('[data-case]').forEach((b) => b.addEventListener('click', () => showCase(b.dataset.case)));
}

async function showCase(cid) {
  document.querySelectorAll('#qCases [data-case]').forEach((b) => b.classList.toggle('active', b.dataset.case === cid));
  let c;
  try { c = await apiGet(`/api/lab/cases/${enc(cid)}`); } catch (e) { toast(e.message, 'error'); return; }
  const pretty = (o) => esc(JSON.stringify(o, null, 2) ?? '—');
  $('qCase').innerHTML = `
    <article class="case">
      <h3>Caso <code>${esc(c.id)}</code></h3>
      <dl class="meta">${c.signals.map((s) => `<dt><span class="sig sig-${esc(s.severity)}">${esc(s.code)}</span></dt><dd>${esc(s.detail)}</dd>`).join('')}</dl>
      <details><summary>Entrada que recibió</summary><pre>${esc(c.user)}</pre></details>
      <div class="compare">
        <div><h4>Salida del alumno</h4><pre>${pretty(c.raw)}</pre></div>
        <div><h4>Salida del maestro</h4><pre>${pretty(c.teacher_raw)}</pre></div>
      </div>
    </article>`;
  $('qCase').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── Eliminar ───────────────────────────────────────────────
function openDelete(m) {
  LAB.deleting = m;
  $('delVersion').textContent = m.version;
  $('delModel').textContent = m.model;
  $('delConfirm').value = '';
  $('delGo').disabled = true;
  $('delOut').textContent = '';
  $('deleteOverlay').classList.remove('hidden');
  $('delConfirm').focus();
}

async function confirmDelete() {
  const m = LAB.deleting;
  if (!m) return;
  try {
    await apiPost('/api/lab/delete', { model: m.model, confirm: $('delConfirm').value });
    $('deleteOverlay').classList.add('hidden');
    toast(`Versión ${m.version} eliminada de Ollama`, 'ok');
    await loadLab();
  } catch (e) { $('delOut').textContent = e.message; }
}

// ── Entrevistas ────────────────────────────────────────────
function newSessionId() {
  return 'ui-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}

function renderInterview() {
  labModelList('iModels', pickInterviewModel, (m) => !m.deleted);
  if (LAB.models.find((m) => m.model === LAB.model)?.deleted) LAB.model = null;
  if (LAB.model) pickInterviewModel(LAB.model);
}

async function pickInterviewModel(model) {
  if (model !== LAB.model || !LAB.session) LAB.session = newSessionId();
  LAB.model = model;
  document.querySelectorAll('#iModels .list-item').forEach((el) => el.classList.toggle('active', el.dataset.model === model));
  $('iEmpty').classList.add('hidden');
  $('iChat').classList.remove('hidden');
  $('iTitle').textContent = model;
  const box = $('iMessages');
  box.innerHTML = '';
  let mem;
  try { mem = await apiGet(`/api/lab/memory?model=${enc(model)}&session=${enc(LAB.session)}`); } catch (e) { toast(e.message, 'error'); return; }
  const turns = mem.sessions.reduce((n, s) => n + s.turns.length, 0);
  $('iMemory').textContent = mem.sessions.length
    ? `Recuerda ${mem.sessions.length} sesiones anteriores (${turns} mensajes) y sus casos de cuarentena.`
    : 'Primera entrevista: recuerda sus casos de cuarentena.';
  $('iPrompt').textContent = mem.system_prompt;
  const current = mem.sessions.find((s) => s.id === LAB.session);
  for (const t of current?.turns || []) chatBubble(box, t.role === 'user' ? 'user' : 'agent', t.text);
  if (!current) box.innerHTML = '<div class="empty-inline">Pregúntale por lo que hizo. Recibe su registro de casos y vuestras conversaciones anteriores; no tiene herramientas, red ni archivos.</div>';
  $('iInput').focus();
}

async function sendInterview() {
  const input = $('iInput');
  const text = input.value.trim();
  if (!text || !LAB.model || LAB.sending) return;
  const box = $('iMessages');
  box.querySelector('.empty-inline')?.remove();
  input.value = ''; autoResize(input);
  LAB.sending = true; $('iSend').disabled = true;
  chatBubble(box, 'user', text, nowHM());
  const bubble = chatBubble(box, 'agent', '');
  bubble.classList.add('pending');
  try {
    await streamSSE('/api/lab/interview', { model: LAB.model, session_id: LAB.session, message: text }, (c) => {
      bubble.textContent += c; box.scrollTop = box.scrollHeight;
    });
    if (!bubble.textContent) bubble.textContent = '(sin respuesta)';
  } catch (e) { bubble.textContent = `No respondió: ${e.message}`; bubble.classList.add('error'); }
  bubble.classList.remove('pending');
  LAB.sending = false; $('iSend').disabled = false;
}

// ── Archivo ────────────────────────────────────────────────
async function renderArchive() {
  let docs = [];
  try { docs = (await apiGet('/api/lab/archive')).docs || []; } catch { /* vacío */ }
  $('aDocs').innerHTML = docs.length ? docs.map((d) => `
    <button class="list-item ${d.name === LAB.doc ? 'active' : ''}" data-doc="${esc(d.name)}">
      <span class="li-title">${icon('doc')}${esc(d.title)}</span>
      <span class="li-meta"><span>${d.entries.length} entradas</span><span>${esc(fmtDate(d.updated))}</span></span>
    </button>`).join('') : '<div class="empty-state"><p>El archivo está vacío.</p><p class="muted">Los diarios de campo se guardan en docs/laboratorio/.</p></div>';
  $('aDocs').querySelectorAll('[data-doc]').forEach((el) => el.addEventListener('click', () => openDoc(el.dataset.doc)));
  if (LAB.doc || docs.length) openDoc(LAB.doc || docs[0].name);
}

async function openDoc(name) {
  LAB.doc = name;
  document.querySelectorAll('#aDocs .list-item').forEach((el) => el.classList.toggle('active', el.dataset.doc === name));
  try {
    const d = await apiGet(`/api/lab/archive/${enc(name)}`);
    $('aDoc').innerHTML = `<article class="prose">${renderMarkdown(d.markdown)}</article>`;
  } catch (e) { $('aDoc').innerHTML = `<p class="muted">No se pudo abrir: ${esc(e.message)}</p>`; }
}

function setupLab() {
  SECTION_LOADERS.lab = loadLab;
  TAB_HOOKS['lab:quarantine'] = renderQuarantine;
  TAB_HOOKS['lab:interview'] = renderInterview;
  TAB_HOOKS['lab:archive'] = renderArchive;
  $('delConfirm').addEventListener('input', () => { $('delGo').disabled = $('delConfirm').value.trim() !== LAB.deleting?.version; });
  $('delConfirm').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !$('delGo').disabled) confirmDelete(); });
  $('delGo').addEventListener('click', confirmDelete);
  $('delCancel').addEventListener('click', () => $('deleteOverlay').classList.add('hidden'));
  $('iSend').addEventListener('click', sendInterview);
  onEnterSend($('iInput'), sendInterview);
  $('iNewSession').addEventListener('click', () => { LAB.session = newSessionId(); pickInterviewModel(LAB.model); });
  $('iShowPrompt').addEventListener('click', () => $('iPromptBox').classList.toggle('hidden'));
}
