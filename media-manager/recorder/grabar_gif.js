#!/usr/bin/env node
/**
 * grabar_gif.js — Graba un GIF de una página web mostrando una funcionalidad.
 *
 * Uso:
 *   node grabar_gif.js <url> <acciones.json> <salida.gif>
 *
 * acciones.json = lista de pasos que el navegador ejecuta mientras graba:
 *   [
 *     {"accion": "esperar", "ms": 1500},
 *     {"accion": "click", "selector": "text=Empezar"},
 *     {"accion": "escribir", "selector": "#respuesta", "texto": "火"},
 *     {"accion": "scroll", "y": 400},
 *     {"accion": "hover", "selector": ".kanji-card"},
 *     {"accion": "tecla", "tecla": "Enter"}
 *   ]
 *
 * Graba en viewport vertical 540x960 (se escala a 1080x1920 en make_reel.sh).
 * El video temporal (webm) se convierte a GIF con ffmpeg + paleta optimizada.
 */
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

async function main() {
  const [url, accionesPath, salida] = process.argv.slice(2);
  if (!url || !accionesPath || !salida) {
    console.error('Uso: node grabar_gif.js <url> <acciones.json> <salida.gif>');
    process.exit(1);
  }
  const acciones = JSON.parse(fs.readFileSync(accionesPath, 'utf8'));
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'gifrec-'));

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 540, height: 960 },
    recordVideo: { dir: tmpDir, size: { width: 540, height: 960 } },
    deviceScaleFactor: 2,
  });
  const page = await context.newPage();
  // 5s por acción: un selector equivocado no debe congelar la grabación 30s.
  page.setDefaultTimeout(5000);

  console.log(`▶ Grabando ${url} …`);
  const t0 = Date.now();
  let marca = 0; // segundos a recortar del inicio del GIF
  await page.goto(url, { waitUntil: 'networkidle' });

  for (const paso of acciones) {
    try {
      switch (paso.accion) {
        case 'esperar': await page.waitForTimeout(paso.ms || 1000); break;
        case 'click': await page.click(paso.selector); break;
        case 'escribir': await page.fill(paso.selector, paso.texto || ''); break;
        case 'tipear': await page.type(paso.selector, paso.texto || '', { delay: paso.delay || 90 }); break;
        case 'scroll': await page.mouse.wheel(0, paso.y || 300); break;
        case 'hover': await page.hover(paso.selector); break;
        case 'tecla': await page.keyboard.press(paso.tecla || 'Enter'); break;
        case 'clickxy': await page.mouse.click(paso.x || 270, paso.y || 480); break;
        case 'ir': await page.goto(paso.url, { waitUntil: 'networkidle' }); break;
        case 'marcar':
          // El GIF empieza aquí: lo anterior (cerrar popups, cookies) se recorta.
          marca = (Date.now() - t0) / 1000;
          console.log(`  ◔ marca de inicio a los ${marca.toFixed(1)}s`);
          break;
        default: console.warn(`  ⚠ acción desconocida: ${paso.accion}`);
      }
    } catch (e) {
      console.warn(`  ⚠ paso falló (${paso.accion} ${paso.selector || ''}): ${e.message.split('\n')[0]}`);
    }
  }
  await page.waitForTimeout(800); // respiro final

  await context.close(); // cierra y guarda el video
  await browser.close();

  const webm = fs.readdirSync(tmpDir).find(f => f.endsWith('.webm'));
  if (!webm) { console.error('✗ No se generó video'); process.exit(1); }
  const webmPath = path.join(tmpDir, webm);

  // webm → GIF con paleta optimizada (mejor calidad, menos peso).
  // Si hubo "marcar", el GIF empieza en ese segundo (recorta los popups).
  const ss = marca > 0 ? ['-ss', marca.toFixed(2)] : [];
  const palette = path.join(tmpDir, 'palette.png');
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', ...ss, '-i', webmPath,
    '-vf', 'fps=12,scale=540:-1:flags=lanczos,palettegen', palette]);
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', ...ss, '-i', webmPath, '-i', palette,
    '-filter_complex', 'fps=12,scale=540:-1:flags=lanczos[x];[x][1:v]paletteuse', salida]);

  fs.rmSync(tmpDir, { recursive: true, force: true });
  const kb = Math.round(fs.statSync(salida).size / 1024);
  console.log(`✓ GIF creado: ${salida} (${kb} KB)`);
}

main().catch(e => { console.error('✗', e.message); process.exit(1); });
