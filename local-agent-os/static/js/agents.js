/* Componentes de agente compartidos por todas las áreas:
   - Panel lateral de chat (agentes del sistema, del pipeline y construidos)
   - Ficha de agente construido (skills, tipo, entrenar, eliminar) */

const DRAWER = { id: null, sending: false };

async function openAgentChat(id, name, role = '') {
  DRAWER.id = id;
  $('drawerName').textContent = name || agentName(id);
  $('drawerRole').textContent = role;
  const sel = $('drawerModel');
  sel.innerHTML = APP.models.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
  if (APP.models.includes(APP.model)) sel.value = APP.model;
  $('drawer').classList.add('open');
  const box = $('drawerMessages');
  box.innerHTML = '';
  try {
    const { history } = await apiGet(`/api/agents/${enc(id)}/chat/history`);
    for (const m of history) chatBubble(box, m.role === 'user' ? 'user' : 'agent', m.role === 'user' ? m.content : stripThink(m.content));
    if (!history.length) box.innerHTML = `<div class="empty-inline">Escribe para hablar con ${esc(name || id)}.</div>`;
  } catch { /* sin historial */ }
  $('drawerInput').focus();
}

function closeAgentChat() {
  DRAWER.id = null;
  $('drawer').classList.remove('open');
}

async function sendDrawer() {
  const input = $('drawerInput');
  const text = input.value.trim();
  if (!text || !DRAWER.id || DRAWER.sending) return;
  const box = $('drawerMessages');
  box.querySelector('.empty-inline')?.remove();
  input.value = ''; autoResize(input);
  DRAWER.sending = true; $('drawerSend').disabled = true;
  chatBubble(box, 'user', text, nowHM());
  const bubble = chatBubble(box, 'agent', '');
  bubble.classList.add('pending');
  let full = '';
  try {
    await streamSSE(`/api/agents/${enc(DRAWER.id)}/chat`, { message: text, model: $('drawerModel').value || APP.model }, (chunk) => {
      full += chunk; bubble.textContent = stripThink(full); box.scrollTop = box.scrollHeight;
    });
  } catch (e) {
    bubble.textContent = `No respondió: ${e.message}`; bubble.classList.add('error');
  }
  bubble.classList.remove('pending');
  DRAWER.sending = false; $('drawerSend').disabled = false;
}

async function clearDrawer() {
  if (!DRAWER.id) return;
  await apiDel(`/api/agents/${enc(DRAWER.id)}/chat/history`);
  $('drawerMessages').innerHTML = '<div class="empty-inline">Historial borrado.</div>';
}

// ── Ficha de agente construido ──────────────────────────────
const CARD = { id: null, skills: [], onChange: null };

async function openAgentCard(id, onChange = null) {
  let d;
  try { d = await apiGet(`/api/factory/agents/${enc(id)}`); }
  catch { openAgentChat(id, agentName(id)); return; }
  CARD.id = id; CARD.onChange = onChange;
  $('cardName').textContent = d.name;
  $('cardTier').textContent = d.tier === 'secondary' ? 'Decide' : 'Ejecuta';
  $('cardTier').className = `tag tag-${d.tier || 'tertiary'}`;
  $('cardProject').textContent = d.project || 'sin proyecto';
  $('cardDesc').textContent = d.description || '';
  const ms = d.model_status || {};
  $('cardMeta').innerHTML = `
    <dt>Lee</dt><dd>${esc((d.reads || []).join(', ') || '—')}</dd>
    <dt>Escribe</dt><dd><code>${esc(d.writes)}</code></dd>
    <dt>Salida</dt><dd>${esc(Object.entries(d.output_schema || {}).map(([k, v]) => `${k}: ${v}`).join(' · ') || '—')}</dd>
    <dt>Herramientas</dt><dd>${esc((d.tools || []).join(', ') || 'ninguna')}</dd>
    <dt>Modelo</dt><dd><code>${esc(ms.engine || ms.model || '—')}</code>${ms.specialized ? ' <span class="tag tag-student">alumno propio</span>' : ''}</dd>`;
  CARD.skills = (d.resolved_skills || []).map((s) => s.id);
  const sk = $('cardSkills');
  sk.innerHTML = (d.resolved_skills || []).length
    ? d.resolved_skills.map((s) => `<span class="chip ${s.missing ? 'chip-missing' : ''}">${esc(s.name)}<button class="chip-x" data-rm="${esc(s.id)}" aria-label="Quitar ${esc(s.name)}">${icon('close')}</button></span>`).join('')
    : '<span class="muted">sin skills</span>';
  sk.querySelectorAll('[data-rm]').forEach((b) => b.addEventListener('click',
    () => editAgentCard({ skills: CARD.skills.filter((x) => x !== b.dataset.rm) })));
  let all = [];
  try { all = (await apiGet('/api/factory/skills')).skills || []; } catch { /* sin catálogo */ }
  const avail = all.filter((s) => !CARD.skills.includes(s.id));
  $('cardSkillPicker').innerHTML = avail.length
    ? avail.map((s) => `<option value="${esc(s.id)}">${esc(s.name || s.id)}</option>`).join('')
    : '<option value="">No quedan skills por añadir</option>';
  $('cardTierSel').value = d.tier || 'tertiary';
  $('cardTrainBox').classList.add('hidden');
  $('cardTrainOut').textContent = '';
  $('cardOverlay').classList.remove('hidden');
}

function closeAgentCard() { $('cardOverlay').classList.add('hidden'); }

async function editAgentCard(patch) {
  if (!CARD.id) return;
  try { await apiPost(`/api/factory/agents/${enc(CARD.id)}/edit`, patch); }
  catch (e) { toast(`No se pudo editar: ${e.message}`, 'error'); return; }
  await openAgentCard(CARD.id, CARD.onChange);
  CARD.onChange?.();
}

async function deleteAgentCard() {
  if (!CARD.id || !confirm(`¿Eliminar el agente «${CARD.id}»? Se borra su spec.`)) return;
  await apiDel(`/api/factory/agents/${enc(CARD.id)}`);
  closeAgentCard();
  toast('Agente eliminado');
  CARD.onChange?.();
}

async function sendCardToTraining() {
  const out = $('cardTrainOut');
  out.textContent = 'Enviando al Entrenador…';
  try {
    const b = await apiPost(`/api/factory/agents/${enc(CARD.id)}/train`, {
      focus: $('cardFocus').value.trim(), material: $('cardMaterial').value.trim(),
    });
    out.textContent = `En la cola del Entrenador (foco: ${b.focus || '—'})`
      + (b.material ? ` · material leído: ${b.material.kind}, ${b.material.chars} caracteres` : '');
  } catch (e) { out.textContent = `No se pudo encolar: ${e.message}`; }
}

function setupAgentComponents() {
  $('drawerClose').addEventListener('click', closeAgentChat);
  $('drawerClear').addEventListener('click', clearDrawer);
  $('drawerSend').addEventListener('click', sendDrawer);
  onEnterSend($('drawerInput'), sendDrawer);

  $('cardClose').addEventListener('click', closeAgentCard);
  $('cardDelete').addEventListener('click', deleteAgentCard);
  $('cardChat').addEventListener('click', () => { const id = CARD.id; closeAgentCard(); openAgentChat(id, $('cardName').textContent); });
  $('cardTrain').addEventListener('click', () => $('cardTrainBox').classList.toggle('hidden'));
  $('cardTrainSend').addEventListener('click', sendCardToTraining);
  $('cardSkillAdd').addEventListener('click', () => {
    const v = $('cardSkillPicker').value;
    if (v) editAgentCard({ skills: [...CARD.skills, v] });
  });
  $('cardTierSel').addEventListener('change', (e) => editAgentCard({ tier: e.target.value }));
  $('cardOverlay').addEventListener('click', (e) => { if (e.target === $('cardOverlay')) closeAgentCard(); });
}
