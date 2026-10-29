import assert from 'node:assert/strict';
import { readFile, mkdir, writeFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { createServer } from 'vite';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const output = path.resolve(process.env.DRONEDREAM_MAP_TEST_OUTPUT || path.join(root, '../artifacts/test-runs/map-library'));
await mkdir(output, { recursive: true });
const previews = JSON.parse(await readFile(path.join(root, 'src/features/autonomy/retiredMapVersions.json'), 'utf8'));
process.env.VITE_PUBLIC_DEMO_CONSOLE = 'true';
process.env.VITE_API_BASE_URL = 'http://127.0.0.1:5204';
process.env.VITE_SUPABASE_URL = 'https://local-build.invalid';
process.env.VITE_SUPABASE_PUBLISHABLE_KEY = 'local-build-placeholder';
const candidatePublic = process.env.DRONEDREAM_MAP_CANDIDATE_PUBLIC;
const servedCandidates = new Set();
const candidatePlugin = {
  name: 'map-candidate-verification',
  configureServer(server) {
    if (!candidatePublic) return;
    server.middlewares.use(async (req, res, next) => {
      const pathname = new URL(req.url, 'http://localhost').pathname.replace(/^\/console(?=\/)/, '');
      if (!/^\/asset-(geometry|previews)\/maps\/[a-z0-9-]+\.(json|jpg|webp)$/.test(pathname)) return next();
      const file = path.join(path.resolve(candidatePublic), pathname.slice(1));
      if (!(await stat(file).catch(() => null))?.isFile()) return next();
      const bytes = await readFile(file);
      servedCandidates.add(pathname);
      res.setHeader('Content-Type', pathname.endsWith('.json') ? 'application/json' : pathname.endsWith('.jpg') ? 'image/jpeg' : 'image/webp');
      res.setHeader('Cache-Control', 'no-store');
      res.end(bytes);
    });
  },
};
const server = await createServer({ root, configFile: path.join(root, 'vite.console.config.ts'), plugins: [candidatePlugin], logLevel: 'warn', server: { host: '127.0.0.1', port: 5204, strictPort: true } });
let browser;
const clearDialog = page => page.evaluate(() => {
  document.querySelector('.account-dialog-backdrop')?.remove();
  document.querySelectorAll('[inert]').forEach(e => e.removeAttribute('inert'));
});
try {
  await server.listen();
  browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.addInitScript(() => localStorage.setItem('drone-dream:locale', 'en'));
  await page.goto('http://127.0.0.1:5204/console/autonomy/maps', { waitUntil: 'networkidle' });
  await page.evaluate(entries => {
    for (const key of [...new Set(['dronedream:autonomy-assets:v1:local:universal', ...Object.keys(localStorage).filter(k => k.startsWith('dronedream:autonomy-assets:'))])]) {
      const library = JSON.parse(localStorage.getItem(key) ?? '{"schemaVersion":2,"aircraft":[],"maps":[]}');
      library.externalAssets = entries.map(e => ({ schemaVersion: 1, id: e.assetId, kind: 'map', name: e.assetId,
        sourceApplication: 'Open-RMF', sourceFormat: 'rmf-building-map-package', version: '1', maturity: 'qualified',
        contentSha256: e.contentSha256, qualificationId: null, importedAt: '2026-10-12T00:00:00Z' }));
      localStorage.setItem(key, JSON.stringify(library));
    }
  }, previews);
  await page.reload({ waitUntil: 'networkidle' });
  await clearDialog(page);
  const grid = page.locator('.autonomy-repository-grid');
  assert.equal(await grid.locator('article').count(), 6); // Current six maps only; retired demos must not return.
  assert.equal(await grid.locator('.autonomy-repository-delete').count(), 6);
  assert.equal(await page.locator('.autonomy-repository-toolbar').count(), 1);
  await page.getByRole('button', { name: 'Import map', exact: true }).click();
  await page.locator('dialog.map-import-dialog').waitFor({ state: 'visible' });
  await page.keyboard.press('Escape');
  const mapNames = ['Kumpula Campus', 'Meilahti Hospital Campus', 'Kalasatama Waterfront',
    'Vuosaari Harbour', 'Suomenlinna Sea Fortress', 'Uutela Coastal Forest'];
  for (const name of mapNames) {
    await grid.locator('article').filter({ hasText: name }).locator('.autonomy-repository-card-surface').dblclick();
    const mapDialog = page.getByRole('dialog', { name, exact: true });
    await mapDialog.locator('canvas').waitFor();
    await page.waitForFunction(() => !document.querySelector('.autonomy-repository-3d-loading'));
    await page.waitForTimeout(500);
    if (candidatePublic) {
      const geometry = JSON.parse(await readFile(path.join(candidatePublic, 'asset-geometry/maps',
        `${name.toLowerCase().replaceAll(' ', '-')}.json`), 'utf8'));
      const metadata = geometry.metadata;
      const row = label => mapDialog.locator('.autonomy-repository-dialog-copy > dl > div')
        .filter({ has: page.locator('dt', { hasText: new RegExp(`^${label}$`) }) }).locator('dd');
      assert.equal(await row('Buildings').innerText(), String(metadata.building_count));
      assert.equal(await row('Size').innerText(), `${metadata.bounds_m.x} × ${metadata.bounds_m.y} × ${metadata.bounds_m.z} m`);
    }
    const mapCanvas = mapDialog.locator('canvas');
    const initial = await mapCanvas.screenshot();
    const bounds = await mapCanvas.boundingBox();
    await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
    await page.mouse.down();
    await page.mouse.move(bounds.x + bounds.width / 2 + 120, bounds.y + bounds.height / 2 + 40, { steps: 12 });
    await page.mouse.up();
    await page.waitForTimeout(300);
    assert.notEqual((await mapCanvas.screenshot()).toString('base64'), initial.toString('base64'), `${name}: 3-D scene must render and rotate`);
    await page.screenshot({ path: path.join(output, `${name.toLowerCase().replaceAll(' ', '-')}-detail.png`) });
    await mapDialog.getByRole('button', { name: 'Close', exact: true }).click();
  }
  await grid.locator('article').filter({ hasText: 'Kumpula Campus' }).locator('.autonomy-repository-card-surface').dblclick();
  const detail = page.getByRole('dialog', { name: 'Kumpula Campus', exact: true });
  await detail.locator('canvas').waitFor();
  await page.waitForFunction(() => !document.querySelector('.autonomy-repository-3d-loading'));
  await page.waitForTimeout(350);
  assert.equal(await detail.locator('.preferred-airspace-view').count(), 0);
  const canvas = detail.locator('canvas');
  const beforeRotation = await canvas.screenshot();
  const canvasBounds = await canvas.boundingBox();
  await page.mouse.move(canvasBounds.x + canvasBounds.width / 2, canvasBounds.y + canvasBounds.height / 2);
  await page.mouse.down();
  await page.mouse.move(canvasBounds.x + canvasBounds.width / 2 + 80, canvasBounds.y + canvasBounds.height / 2 + 30, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(250);
  assert.notEqual((await canvas.screenshot()).toString('base64'), beforeRotation.toString('base64'));
  for (const viewport of [{ width: 1100, height: 700 }, { width: 1920, height: 1080 }]) {
    await page.setViewportSize(viewport);
    assert(await detail.evaluate(el => {
      const copy = el.querySelector('.autonomy-repository-dialog-copy');
      const rect = el.getBoundingClientRect();
      return copy.scrollHeight <= copy.clientHeight + 1 && rect.bottom <= innerHeight && rect.top >= 0;
    }));
    await page.screenshot({ path: path.join(output, `campus-detail-${viewport.width}.png`) });
  }
  await detail.getByRole('button', { name: 'Close', exact: true }).click();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.reload({ waitUntil: 'networkidle' }); await clearDialog(page);
  await page.screenshot({ path: path.join(output, 'map-library.png') });
  const first = grid.locator('article').filter({ hasText: 'Kumpula Campus' });
  await first.locator('.autonomy-repository-delete').click();
  assert.equal(await first.count(), 0);
  await page.reload({ waitUntil: 'networkidle' }); await clearDialog(page);
  assert.equal(await grid.locator('article').filter({ hasText: 'Kumpula Campus' }).count(), 0, 'Deleted default map must remain deleted after reload');
  await page.goto('http://127.0.0.1:5204/console/autonomy', { waitUntil: 'networkidle' });
  await clearDialog(page);
  await page.locator('.assistant-add-button').click();
  await page.getByRole('menuitem', { name: 'Select map', exact: true }).hover();
  assert.equal(await page.getByRole('menuitemradio', { name: 'Kumpula Campus', exact: true }).count(), 0, 'Deleted maps must not remain in Select Map');
  if (candidatePublic) {
    for (const name of mapNames) {
      const url = `/asset-geometry/maps/${name.toLowerCase().replaceAll(' ', '-')}.json`;
      assert(servedCandidates.has(url), `${name}: candidate geometry was not served`);
      const response = await page.request.get(`http://127.0.0.1:5204/console${url}`);
      assert.deepEqual(await response.body(), await readFile(path.join(candidatePublic, url.slice(1))));
    }
  }
  await writeFile(path.join(output, 'result.json'), JSON.stringify({ passed: true, checkedMaps: mapNames, candidatePublic: candidatePublic || null, retiredDemosRemoved: 7, deletionPersists: true, detailWidths: [1100, 1920] }, null, 2));
  console.log(output);
} finally { await browser?.close(); await server.close(); }
