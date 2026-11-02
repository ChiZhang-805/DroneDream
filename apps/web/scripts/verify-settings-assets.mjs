import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { createServer } from 'vite';
const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
process.env.VITE_PUBLIC_DEMO_CONSOLE = 'true';
process.env.VITE_API_BASE_URL = 'http://127.0.0.1:5205';
process.env.VITE_SUPABASE_URL = 'https://local-build.invalid';
process.env.VITE_SUPABASE_PUBLISHABLE_KEY = 'local-build-placeholder';
const server = await createServer({ root, configFile: path.join(root, 'vite.console.config.ts'), logLevel: 'warn', server: { host: '127.0.0.1', port: 5205, strictPort: true } });
let browser;
try {
  await server.listen();
  browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage();
  await page.addInitScript(() => {
    localStorage.setItem('drone-dream:locale', 'en');
    window.__TAURI__ = { core: { invoke: async command => {
      if (command === 'probe_system_prerequisites') return { platform: 'windows', supported: true, windows: { caption: 'Windows 11', version: '10.0.26100', buildNumber: '26100', architecture: '64-bit' }, wsl: { executableAvailable: true, distributions: [{ name: 'DroneDreamRuntime', version: 2, isDefault: false }] }, memory: { totalBytes: 34359738368, availableBytes: 17179869184 }, disks: [{ drive: 'Q:', totalBytes: 1099511627776, freeBytes: 536870912000, isSystemDrive: false }], gpus: [{ name: 'NVIDIA GeForce RTX', driverVersion: '32.0', adapterRamBytes: 8589934592 }], probeErrors: [] };
      if (command === 'probe_runtime_status') return { runtimeName: 'DroneDreamRuntime', installed: true, running: true, ready: true, version: '0.1.0', dataRoot: 'Q:\\DroneDream', components: ['wsl-runtime','host-ownership','runtime-manifest','local-backend','px4','gazebo'].map(id => ({ id, label: id, status: 'ready', required: true, version: null, detail: null })), diagnostics: [] };
      if (command === 'restore_browser_auth_vault') return null;
      if (command === 'get_installer_locale') return 'en';
      if (command === 'get_installer_runtime_intent') return { status: 'none', mode: null, targetRoot: null, message: null };
      throw Error(`Unmocked ${command}`);
    } } };
  });
  for (const viewport of [{width:1280,height:800},{width:1920,height:1080}]) {
    await page.setViewportSize(viewport);
    await page.goto('http://127.0.0.1:5205/console/assistant?docsPreview=1', {waitUntil:'networkidle'});
    if (!await page.locator('.settings-workspace-host').isVisible()) {
      await page.locator('.launcher-settings-button').click();
      await page.getByRole('button', {name:'All settings',exact:true}).click();
    }
    await page.getByRole('tab', {name:'Models',exact:true}).click();
    for (const range of ['7 days','30 days','1 year']) {
      await page.getByRole('tab', {name:range,exact:true}).click();
      const metrics = await page.locator('.settings-model-history-section').evaluate(el => {
        const r=el.getBoundingClientRect();
        const cell=el.querySelector('.settings-allowance-heatmap i')?.getBoundingClientRect();
        const chart=el.querySelector('[data-testid="settings-allowance-chart"]')?.getBoundingClientRect();
        return { bottom:r.bottom, viewport:innerHeight, height:r.height, scroll:el.scrollHeight, client:el.clientHeight, square:cell ? Math.abs(cell.width-cell.height) : null, chartHeight:chart?.height };
      });
      assert(metrics.bottom <= viewport.height + 1 && metrics.scroll <= metrics.client+2, JSON.stringify(metrics));
      if(range==='1 year') assert(metrics.square<1,JSON.stringify(metrics));
    }
    await page.getByRole('tab', {name:'Runtime',exact:true}).click();
    await page.getByRole('button', {name:'Check environment',exact:true}).click();
    await page.waitForFunction(() => document.querySelectorAll('.settings-runtime-check-steps > li').length === 11);
    assert.equal(await page.locator('.settings-runtime-check-steps > li').count(),11);
    assert.equal(await page.locator('.settings-update-versions > div').count(),4);
    const runtime=await page.locator('.settings-runtime-panel').evaluate(el=>({
      bottom:el.getBoundingClientRect().bottom,
      rows:[...el.querySelectorAll('li,.settings-update-versions > div')].map(row=>({h:row.getBoundingClientRect().height,scroll:row.scrollHeight,client:row.clientHeight}))
    }));
    if(viewport.width>1320) assert(runtime.bottom<=viewport.height+1,JSON.stringify(runtime));
    assert(runtime.rows.every(r=>r.h>=40 && r.scroll<=r.client+2),JSON.stringify(runtime));
  }
  console.log('Settings layout verified at 1280x800 and 1920x1080.');
} finally { await browser?.close(); await server.close(); }
