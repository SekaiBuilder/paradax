/* Área Automatización: programaciones de todos los proyectos + Gestor. */

const AUTO = { days: new Set(), sending: false };

async function loadAutomation() {
  let schedules = [], projects = [];
  try {
    const [s, p] = await Promise.all([apiGet('/api/automation/schedules'), apiGet('/api/projects')]);
    schedules = s.schedules || []; projects = p.projects || [];
  } catch { /* servidor caído */ }
  const name = (id) => (projects.find((p) => p.id === id) || { name: id }).name;
  const sel = $('autoProj');
  const prev = sel.value;
  sel.innerHTML = projects.length
    ? projects.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')
    : '<option value="">Crea primero un proyecto</option>';
  if (prev && projects.some((p) => p.id === prev)) sel.value = prev;
  buildDayGrid($('autoDays'), AUTO.days);
  const box = $('autoList');
  box.innerHTML = schedules.length ? schedules.map((s) => scheduleRow(s, name(s.project_id))).join('')
    : '<p class="muted">Sin programaciones. Créalas aquí, desde un proyecto, o pídeselas al Gestor.</p>';
  wireScheduleRows(box, loadAutomation);
}

async function addAutoSchedule() {
  const pid = $('autoProj').value, days = [...AUTO.days], time = $('autoTime').value;
  if (!pid) { toast('Elige un proyecto', 'error'); return; }
  if (!days.length || !time) { toast('Elige al menos un día y la hora límite', 'error'); return; }
  try {
    await apiPost('/api/automation/schedules', { project_id: pid, deadline_time: time, days_of_month: days, label: '' });
    AUTO.days.clear();
    $('autoDays').querySelectorAll('.sel').forEach((c) => c.classList.remove('sel'));
    toast('Programado'); loadAutomation();
  } catch (e) { toast(e.message, 'error'); }
}

async function sendAuto() {
  const input = $('autoInput');
  const text = input.value.trim();
  if (!text || AUTO.sending) return;
  input.value = ''; autoResize(input);
  const box = $('autoMessages');
  box.querySelector('.empty-inline')?.remove();
  chatBubble(box, 'user', text, nowHM());
  const bubble = chatBubble(box, 'agent', '');
  bubble.classList.add('pending');
  AUTO.sending = true;
  try {
    await streamSSE('/api/agents/automation_manager/chat', { message: text, model: APP.model }, (c) => {
      bubble.textContent += c; box.scrollTop = box.scrollHeight;
    });
  } catch (e) { bubble.textContent = `No respondió: ${e.message}`; bubble.classList.add('error'); }
  bubble.classList.remove('pending');
  AUTO.sending = false;
  loadAutomation();
}

function setupAutomation() {
  SECTION_LOADERS.automation = loadAutomation;
  $('autoAdd').addEventListener('click', addAutoSchedule);
  $('autoSend').addEventListener('click', sendAuto);
  onEnterSend($('autoInput'), sendAuto);
}
