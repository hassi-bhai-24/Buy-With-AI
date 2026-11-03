import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from '@playwright/test';

// Playwright resolves relative webServer `cwd` unreliably in this
// sandbox (spawn /bin/sh ENOENT); resolve absolute paths from this file.
const configDir = path.dirname(fileURLToPath(import.meta.url));
const backendDir = path.resolve(configDir, '..', 'backend');

/**
 * Buy with AI end-to-end tests. The backend runs against a throwaway
 * SQLite file (DATABASE_URL) seeded with the labelled-estimate
 * baselines, so E2E runs never touch the developer database.
 * No Ollama is required: verdicts use the labelled rule-based engine.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:3000',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: [
    {
      // Seed (runs migrations first) then serve the backend on :8000.
      command:
        'bash -c "DATABASE_URL=sqlite+aiosqlite:////tmp/buywithai-e2e.db .venv/bin/python scripts/seed-baselines.py && DATABASE_URL=sqlite+aiosqlite:////tmp/buywithai-e2e.db exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000"',
      cwd: backendDir,
      url: 'http://127.0.0.1:8000/api/v1/health',
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 3000',
      cwd: configDir,
      url: 'http://127.0.0.1:3000',
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
});
