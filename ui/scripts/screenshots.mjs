/**
 * Playwright screenshot pipeline for claw-forge Kanban UI
 * Run: node scripts/screenshots.mjs (from repo root or ui/ dir)
 */

import { chromium } from '@playwright/test';
import { spawn, execSync } from 'child_process';
import { mkdir } from 'fs/promises';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import http from 'http';

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, '../..');
const SCREENSHOTS_DIR = resolve(REPO_ROOT, 'website/assets/screenshots');

const SCREENSHOTS = [
  {
    name: "kanban-overview",
    description: "Full Kanban board with all columns",
    viewport: { width: 1440, height: 900 },
    actions: [],
    path: resolve(SCREENSHOTS_DIR, 'kanban-overview.png'),
  },
  {
    name: "kanban-dark",
    description: "Dark mode view",
    viewport: { width: 1440, height: 900 },
    actions: [{ click: 'button[title="Toggle dark mode (D)"]' }],
    path: resolve(SCREENSHOTS_DIR, 'kanban-dark.png'),
  },
  {
    name: "feature-detail",
    description: "Feature detail drawer open",
    viewport: { width: 1440, height: 900 },
    actions: [{ click: '.cursor-pointer' }],
    path: resolve(SCREENSHOTS_DIR, 'feature-detail.png'),
  },
  {
    name: "command-palette",
    description: "Command palette open (Ctrl+K)",
    viewport: { width: 1440, height: 900 },
    actions: [{ keyboard: 'Control+k' }],
    path: resolve(SCREENSHOTS_DIR, 'command-palette.png'),
  },
  {
    name: "pool-status",
    description: "Provider pool health panel (always visible in header)",
    viewport: { width: 1440, height: 900 },
    actions: [],
    path: resolve(SCREENSHOTS_DIR, 'pool-status.png'),
  },
  {
    name: "regression-bar",
    description: "Regression health bar passing",
    viewport: { width: 1440, height: 900 },
    actions: [],
    crop: { x: 0, y: 0, width: 1440, height: 120 },
    path: resolve(SCREENSHOTS_DIR, 'regression-bar.png'),
  },
  {
    name: "mobile-view",
    description: "Mobile responsive view",
    viewport: { width: 390, height: 844 },
    actions: [],
    path: resolve(SCREENSHOTS_DIR, 'mobile-view.png'),
  },
];

function waitForPort(port, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    function attempt() {
      const req = http.get(`http://localhost:${port}`, (res) => {
        resolve();
      });
      req.on('error', () => {
        if (Date.now() - start > timeoutMs) {
          reject(new Error(`Port ${port} not ready after ${timeoutMs}ms`));
        } else {
          setTimeout(attempt, 500);
        }
      });
      req.setTimeout(1000, () => { req.destroy(); });
    }
    attempt();
  });
}

function spawnServer(cmd, args, opts = {}) {
  const proc = spawn(cmd, args, { stdio: 'pipe', ...opts });
  proc.stdout?.on('data', d => process.stdout.write(`[${cmd}] ${d}`));
  proc.stderr?.on('data', d => process.stderr.write(`[${cmd}] ${d}`));
  return proc;
}

async function runAction(page, action) {
  if (action.click) {
    const selectors = action.click.split(',').map(s => s.trim());
    let clicked = false;
    for (const sel of selectors) {
      try {
        const el = await page.$(sel);
        if (el) {
          await el.click({ timeout: 2000 });
          await page.waitForTimeout(800);
          clicked = true;
          break;
        }
      } catch (e) { }
    }
    if (!clicked) {
      console.log(`  ⚠️  No element found for click: ${action.click}`);
    }
  } else if (action.keyboard) {
    await page.keyboard.press(action.keyboard);
    await page.waitForTimeout(800);
  }
}

async function main() {
  await mkdir(SCREENSHOTS_DIR, { recursive: true });

  // Kill stale servers
  try { execSync('fuser -k 8888/tcp 2>/dev/null || true', { stdio: 'ignore' }); } catch(e) {}
  try { execSync('fuser -k 5173/tcp 2>/dev/null || true', { stdio: 'ignore' }); } catch(e) {}
  await new Promise(r => setTimeout(r, 600));

  // Start mock server
  const mockServer = spawnServer('node', [resolve(__dirname, 'mock-server.js')]);
  await waitForPort(8888, 8000);
  console.log('✅ Mock server ready on port 8888');

  // Start Vite dev server from ui/ directory
  const uiDir = resolve(__dirname, '..');
  const viteServer = spawnServer('npm', ['run', 'dev'], { cwd: uiDir });

  console.log('Waiting for Vite dev server on port 5173...');
  await waitForPort(5173, 30000);
  console.log('✅ Dev server ready on port 5173');
  await new Promise(r => setTimeout(r, 2000)); // let React hydrate

  const browser = await chromium.launch({
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  const results = [];

  for (const shot of SCREENSHOTS) {
    console.log(`📸 Capturing: ${shot.name} — ${shot.description}`);
    const context = await browser.newContext({ viewport: shot.viewport });
    const page = await context.newPage();

    try {
      await page.goto('http://localhost:5173/?session=sess_demo_001', { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(1500); // let data load

      for (const action of (shot.actions || [])) {
        await runAction(page, action);
      }

      await page.waitForTimeout(500);

      if (shot.crop) {
        await page.screenshot({ path: shot.path, clip: shot.crop });
      } else {
        await page.screenshot({ path: shot.path, fullPage: false });
      }

      console.log(`  ✅ Saved: ${shot.path}`);
      results.push({ name: shot.name, success: true });
    } catch (err) {
      console.error(`  ❌ Failed: ${shot.name} — ${err.message}`);
      try {
        await page.screenshot({ path: shot.path });
        results.push({ name: shot.name, success: true, note: 'captured despite action error' });
        console.log(`  ✅ Saved (fallback): ${shot.path}`);
      } catch (e2) {
        results.push({ name: shot.name, success: false, error: err.message });
      }
    }

    await context.close();
  }

  await browser.close();
  mockServer.kill();
  viteServer.kill();
  // Ensure ports are freed
  try { execSync('fuser -k 8888/tcp 2>/dev/null || true', { stdio: 'ignore' }); } catch(e) {}
  try { execSync('fuser -k 5173/tcp 2>/dev/null || true', { stdio: 'ignore' }); } catch(e) {}

  const succeeded = results.filter(r => r.success).length;
  const failed = results.filter(r => !r.success).length;
  console.log(`\n✅ ${succeeded} screenshots saved to website/assets/screenshots/`);
  if (failed) console.log(`❌ ${failed} failed: ${results.filter(r => !r.success).map(r => r.name).join(', ')}`);

  process.exit(failed > 0 ? 1 : 0);
}

main().catch(err => {
  console.error('Fatal:', err);
  process.exit(1);
});
