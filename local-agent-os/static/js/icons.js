/* Iconos de Paradax: trazo de 1.6 en una rejilla de 20×20, hechos para la app.
   icon('nombre') devuelve el SVG como texto; hereda el color con currentColor. */

const ICON_PATHS = {
  // Áreas
  projects:   '<rect x="3" y="4" width="14" height="12" rx="1.5"/><path d="M3 8h14M7 8v8"/>',
  constructor:'<path d="M10 2.5l6.5 3.75v7.5L10 17.5l-6.5-3.75v-7.5z"/><path d="M10 7v6M7 10h6"/>',
  training:   '<path d="M3 15h3.5v-3.5H10V8h3.5V4.5H17"/><path d="M14.5 2.5L17 4.5l-2.5 2"/>',
  lab:        '<path d="M8 2.5h4M8.75 2.5v5L4 15.25A1.5 1.5 0 0 0 5.3 17.5h9.4a1.5 1.5 0 0 0 1.3-2.25L11.25 7.5v-5"/><path d="M6 12.5h8"/>',
  automation: '<circle cx="10" cy="10.5" r="6.5"/><path d="M10 7v3.5l2.5 1.5M7.5 2h5"/>',
  activity:   '<path d="M2.5 10.5h3l2-5 3 9 2-6 1.5 2h3.5"/>',
  // Acciones
  play:       '<path d="M6 4l10 6-10 6z"/>',
  plus:       '<path d="M10 4v12M4 10h12"/>',
  build:      '<path d="M10 2.5l6.5 3.75v7.5L10 17.5l-6.5-3.75v-7.5z"/><path d="M10 10l6.5-3.75M10 10v7.5M10 10L3.5 6.25"/>',
  undo:       '<path d="M6.5 5L3 8.5 6.5 12"/><path d="M3 8.5h9a4.5 4.5 0 0 1 0 9H8"/>',
  trash:      '<path d="M4 5.5h12M8 5.5V3.5h4v2M5.5 5.5l.75 11h7.5l.75-11"/>',
  send:       '<path d="M3 10l14-6.5L12 17l-2.5-5.5z"/><path d="M9.5 11.5L17 3.5"/>',
  close:      '<path d="M5 5l10 10M15 5L5 15"/>',
  back:       '<path d="M12 4l-6 6 6 6"/>',
  chat:       '<path d="M3.5 4.5h13v9H9l-4 3v-3H3.5z"/>',
  folder:     '<path d="M2.5 5.5a1 1 0 0 1 1-1h4l1.5 2h7.5a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-13a1 1 0 0 1-1-1z"/>',
  doc:        '<path d="M5 2.5h6.5L15 6v11.5H5z"/><path d="M11.5 2.5V6H15M7.5 10h5M7.5 13h5"/>',
  calendar:   '<rect x="3" y="4.5" width="14" height="12" rx="1.5"/><path d="M3 8.5h14M7 2.5v3.5M13 2.5v3.5"/>',
  flag:       '<path d="M5 17.5V3M5 3.5h9l-2 3.5 2 3.5H5"/>',
  manual:     '<circle cx="10" cy="10" r="2.5"/><path d="M10 2.5v2.5M10 15v2.5M2.5 10H5M15 10h2.5M4.7 4.7l1.8 1.8M13.5 13.5l1.8 1.8M4.7 15.3l1.8-1.8M13.5 6.5l1.8-1.8"/>',
  auto:       '<path d="M15.5 7A6 6 0 0 0 4.3 7.5M4.5 13a6 6 0 0 0 11.2-.5"/><path d="M15.5 3v4h-4M4.5 17v-4h4"/>',
  shield:     '<path d="M10 2.5l6 2.5v4.5c0 4-2.75 6.75-6 8-3.25-1.25-6-4-6-8V5z"/>',
  hazard:     '<path d="M10 3L17.5 16.5h-15z"/><path d="M10 8.5v3.5M10 14.25v.25"/>',
  memory:     '<rect x="4" y="5" width="12" height="10" rx="1.5"/><path d="M7 5V3M10 5V3M13 5V3M7 17v-2M10 17v-2M13 17v-2M7 8.5h6v3H7z"/>',
  eye:        '<path d="M2 10s3-5.5 8-5.5S18 10 18 10s-3 5.5-8 5.5S2 10 2 10z"/><circle cx="10" cy="10" r="2.5"/>',
  release:    '<rect x="4.5" y="9" width="11" height="8" rx="1.5"/><path d="M7 9V6.5a3 3 0 0 1 5.8-1"/>',
  info:       '<circle cx="10" cy="10" r="7.5"/><path d="M10 9v5M10 6.25v.25"/>',
  check:      '<path d="M4 10.5l4 4 8-9"/>',
  star:       '<path d="M10 2.5l2.3 4.8 5.2.7-3.8 3.6.9 5.2L10 14.3l-4.6 2.5.9-5.2L2.5 8l5.2-.7z"/>',
  graduate:   '<path d="M10 4L2 8l8 4 8-4z"/><path d="M5.5 9.75V13.5c0 1 2 2.5 4.5 2.5s4.5-1.5 4.5-2.5V9.75M17.5 8v4.5"/>',
  skill:      '<path d="M10 2.5l1.9 4.3 4.6.4-3.5 3 1 4.6L10 12.4l-4 2.4 1-4.6-3.5-3 4.6-.4z"/>',
  ghost:      '<path d="M5 17V9a5 5 0 0 1 10 0v8l-2-1.5-1.75 1.5L10 15.5 8.75 17 7 15.5z"/><path d="M8 9h.01M12 9h.01"/>',
  terminal:   '<rect x="2.5" y="3.5" width="15" height="13" rx="1.5"/><path d="M6 8l2.5 2L6 12M10.5 12.5H14"/>',
  list:       '<path d="M7 5.5h10M7 10h10M7 14.5h10M3 5.5h.01M3 10h.01M3 14.5h.01"/>',
  hierarchy:  '<rect x="7.5" y="2.5" width="5" height="4" rx="1"/><rect x="2.5" y="13.5" width="5" height="4" rx="1"/><rect x="12.5" y="13.5" width="5" height="4" rx="1"/><path d="M10 6.5v3.5M5 13.5V10h10v3.5"/>',
  team:       '<circle cx="7" cy="7" r="2.5"/><circle cx="14" cy="8" r="2"/><path d="M2.5 16.5c.5-3 2.25-4.5 4.5-4.5s4 1.5 4.5 4.5M12 12.5c2.5-.5 4.75.75 5.5 4"/>',
  open:       '<path d="M11 3.5h5.5V9M16.5 3.5L9 11M14 12.5v4H3.5V6h4"/>',
  refresh:    '<path d="M16 6.5A6.5 6.5 0 1 0 16.5 12"/><path d="M16.5 2.5v4h-4"/>',
};

function icon(name, cls = '') {
  const p = ICON_PATHS[name];
  if (!p) return '';
  return `<svg class="ic ${cls}" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`;
}

// Rellena todos los <i data-icon="x"> del documento (los del HTML estático).
function hydrateIcons(root = document) {
  root.querySelectorAll('i[data-icon]').forEach((el) => {
    el.outerHTML = icon(el.dataset.icon, el.className || '');
  });
}
