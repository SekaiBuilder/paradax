/* Arranque: navegación, componentes, datos iniciales y eventos en vivo. */

async function boot() {
  setupI18n();
  hydrateIcons();
  setupTabs();
  setupAgentComponents();
  setupProjects();
  setupFactory();
  setupTraining();
  setupLab();
  setupAutomation();
  setupActivity();

  document.querySelectorAll('.nav-item').forEach((b) => b.addEventListener('click', () => showSection(b.dataset.section)));
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    closeAgentChat();
    document.querySelectorAll('.overlay:not(.hidden)').forEach((o) => o.classList.add('hidden'));
  });
  document.querySelectorAll('.overlay').forEach((o) => o.addEventListener('click', (e) => { if (e.target === o) o.classList.add('hidden'); }));

  const [models, health, agents] = await Promise.allSettled([
    apiGet('/api/models'), apiGet('/api/health'), apiGet('/api/agents?project=all'),
  ]);
  if (models.status === 'fulfilled') APP.models = models.value.models || [];
  if (health.status === 'fulfilled') {
    APP.model = health.value.default_model || APP.models[0] || '';
    $('engine').textContent = APP.model;
    $('engineDot').classList.add('ok');
  } else {
    $('engine').textContent = 'Servidor sin respuesta';
    $('engineDot').classList.add('bad');
  }
  if (agents.status === 'fulfilled') for (const a of agents.value.agents || []) APP.agentNames.set(a.id, a.name);
  try {
    const sys = await apiGet('/api/system/agents');
    for (const a of sys.agents) APP.agentNames.set(a.id, a.name);
  } catch { /* nombres por id */ }

  // Contadores de la barra lateral sin esperar a entrar en cada área.
  apiGet('/api/lab/overview').then((d) => { $('labCount').textContent = (d.models || []).filter((m) => m.vetoed).length || ''; }).catch(() => {});
  apiGet('/api/factory/ghost/pending').then((d) => { $('ghostCount').textContent = (d.pending || []).length || ''; }).catch(() => {});

  try {
    const snap = await apiGet('/api/activity');
    for (const ev of snap.events || []) handleEvent(ev, true);
  } catch { /* el stream igual llega */ }
  connectEvents();

  let start = 'projects';
  try { start = localStorage.getItem('paradax.section') || 'projects'; } catch { /* sin storage */ }
  showSection(document.getElementById(`sec-${start}`) ? start : 'projects');
}

boot().catch((e) => { console.error(e); toast(`Error al arrancar: ${e.message}`, 'error'); });
