import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { createServer } from 'vite';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const output = path.resolve(process.env.DRONEDREAM_AIRCRAFT_TEST_OUTPUT || path.join(root, '../artifacts/test-runs/aircraft-library'));
await mkdir(output, { recursive: true });
process.env.VITE_PUBLIC_DEMO_CONSOLE = 'true';
process.env.VITE_API_BASE_URL = 'http://127.0.0.1:5205';
process.env.VITE_SUPABASE_URL = 'https://local-build.invalid';
process.env.VITE_SUPABASE_PUBLISHABLE_KEY = 'local-build-placeholder';
const server = await createServer({ root, configFile: path.join(root, 'vite.console.config.ts'), logLevel: 'warn',
  plugins: [{ name: 'aircraft-preview-validation', configureServer(server) {
    server.middlewares.use('/__aircraft-preview', async (_request, response) => {
      response.setHeader('Content-Type', 'text/html');
      response.end(await server.transformIndexHtml('/__aircraft-preview', `<html><body style="margin:0"><div id="root" style="width:960px;height:560px"></div>
        <style>.autonomy-repository-3d-view{width:100%;height:100%}canvas{display:block}</style>
        <script type="module">
          import React from 'react';
          import {createRoot} from 'react-dom/client';
          import {RepositoryAsset3DView} from '/src/features/autonomy/RepositoryAsset3DView.tsx';
          const key = new URLSearchParams(location.search).get('key');
          createRoot(document.getElementById('root')).render(React.createElement(RepositoryAsset3DView,
            {kind:'vehicle',previewKey:key,name:key,chinese:false}));
        </script></body></html>`));
    });
  } }], server: { host: '127.0.0.1', port: 5205, strictPort: true } });
let browser;
try {
  await server.listen();
  browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem('drone-dream:locale', 'en'));
  await page.goto('http://127.0.0.1:5205/console/autonomy/aircraft', { waitUntil: 'networkidle' });
  await page.evaluate(() => {
    document.querySelector('.account-dialog-backdrop')?.remove();
    document.querySelectorAll('[inert]').forEach(e => e.removeAttribute('inert'));
  });
  const cards = page.locator('.autonomy-repository-grid article');
  assert.equal(await cards.count(), 6);
  const catalog = JSON.parse(await readFile(path.join(root, 'public/asset-geometry/vehicles/catalog.json'), 'utf8'));
  const models = [];
  for (let i = 0; i < 6; i++) {
    const name = (await cards.nth(i).innerText()).trim();
    const downloaded = page.waitForResponse(response => response.url().endsWith('.glb'));
    await cards.nth(i).locator('.autonomy-repository-card-surface').dblclick();
    const response = await downloaded;
    assert(response.ok(), `${name}: source model must load`);
    const key = path.basename(new URL(response.url()).pathname, '.glb');
    const dialog = page.locator('.autonomy-repository-dialog');
    await page.waitForFunction(() => !document.querySelector('.autonomy-repository-3d-loading'));
    assert.equal(await dialog.getByText('3D view is unavailable on this device.', { exact: true }).count(), 0);
    const canvas = dialog.locator('canvas');
    await page.waitForTimeout(400);
    const metadata = catalog.models.find(model => model.preview_key === key);
    assert(metadata, `${name}: source metadata must exist`);
    const row = label => dialog.locator('.autonomy-repository-dialog-copy > dl > div')
      .filter({ has: page.locator('dt', { hasText: new RegExp(`^${label}$`) }) }).locator('dd');
    assert.equal(await row('Dry mass').innerText(), `${Number(metadata.mass_kg.toFixed(3))} kg`);
    assert.equal(await row('Model size').innerText(), `${[0, 2, 1].map(axis => Number(metadata.visual_size_m[axis].toFixed(3))).join(' × ')} m`);
    await page.screenshot({ path: path.join(output, `${key}-detail.png`) });
    const first = await canvas.screenshot({ path: path.join(output, `${key}.png`) });
    const bounds = await canvas.boundingBox();
    const center = { x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2 };
    await page.mouse.move(center.x, center.y);
    await page.mouse.down();
    await page.mouse.move(center.x + 130, center.y + 35, { steps: 12 });
    await page.mouse.up();
    await page.waitForTimeout(400);
    const second = await canvas.screenshot({ path: path.join(output, `${key}-rotated.png`) });
    assert.notEqual(first.toString('base64'), second.toString('base64'), `${name}: actual model must render and rotate`);
    // Locate a real mesh by sampling the central region; selection must expose a source part.
    let selected = false;
    for (const dy of [0, -0.1, 0.1]) {
      for (const dx of [0, -0.1, 0.1, -0.2, 0.2]) {
        await page.mouse.click(center.x + bounds.width * dx, center.y + bounds.height * dy);
        selected = await page.locator('.autonomy-vehicle-part-card').count() > 0;
        if (selected) break;
      }
      if (selected) break;
    }
    assert(selected, `${name}: source part selection must work`);
    models.push({ key, name, part: await page.locator('.autonomy-vehicle-part-card').innerText() });
    await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  }
  assert.deepEqual(errors, []);
  assert.equal(catalog.models.length, 13);
  assert(catalog.models.every(model => model.invalid_inertia_links.length === 0));
  const writePreviews = process.argv.includes('--write-previews');
  for (const model of catalog.models) {
    const key = model.preview_key;
    await page.goto(`http://127.0.0.1:5205/__aircraft-preview?key=${key}`, { waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.querySelector('canvas') && !document.querySelector('.autonomy-repository-3d-loading'));
    assert.equal(await page.getByText('3D view is unavailable on this device.', { exact: true }).count(), 0);
    const canvas = page.locator('canvas');
    await page.waitForTimeout(300);
    assert.deepEqual(await canvas.evaluate(element => [element.clientWidth, element.clientHeight]), [960, 560]);
    const png = await canvas.screenshot({ path: path.join(output, `${key}-source.png`) });
    if (writePreviews) {
      const encoded = await page.evaluate(async base64 => {
        const image = new Image();
        image.src = `data:image/png;base64,${base64}`;
        await image.decode();
        const canvas = document.createElement('canvas');
        canvas.width = image.width; canvas.height = image.height;
        canvas.getContext('2d').drawImage(image, 0, 0);
        return canvas.toDataURL('image/webp', 0.9).split(',')[1];
      }, png.toString('base64'));
      await writeFile(path.join(root, `public/asset-previews/vehicles/${key}.webp`), Buffer.from(encoded, 'base64'));
    }
  }
  assert.deepEqual(errors, []);
  if (writePreviews) {
    const manifestPath = path.join(root, 'public/asset-previews/manifest.json');
    const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
    manifest.sources.vehicles.commit = catalog.revision;
    manifest.sources.vehicles.generator = 'scripts/verify-aircraft-library.mjs --write-previews';
    for (const file of manifest.files) {
      const bytes = await readFile(path.join(root, 'public/asset-previews', file.path));
      file.bytes = bytes.length;
      file.sha256 = createHash('sha256').update(bytes).digest('hex');
    }
    await writeFile(manifestPath, JSON.stringify(manifest, null, 2) + '\n');
  }
  await writeFile(path.join(output, 'result.json'), JSON.stringify({ passed: true, models, sourceRevision: catalog.revision }, null, 2));
  console.log(output);
} finally {
  await browser?.close();
  await server.close();
}
