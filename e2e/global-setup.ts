import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';

const PROJECT = 'aisc-e2e';
const repoRoot = path.resolve(__dirname, '..');
const envFile = path.join(__dirname, '.env.e2e');
const port = process.env.E2E_PORT ?? '8080';
const base = `http://localhost:${port}`;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Build a throwaway env file from env.example so the stack binds to E2E_PORT
 * without touching the developer's own `.env`.
 */
function generateEnvFile(): void {
  const overrides: Record<string, string> = {
    CADDY_HOST_PORT: port,
    API_URL_EXTERNAL: base,
    KEYCLOAK_URL_EXTERNAL: `${base}/auth`,
    KEYCLOAK_ISSUER: `${base}/auth/realms/aisc`,
  };
  if (process.env.AISC_IMAGE_TAG) overrides.AISC_IMAGE_TAG = process.env.AISC_IMAGE_TAG;

  let text = readFileSync(path.join(repoRoot, 'env.example'), 'utf8');
  for (const [key, value] of Object.entries(overrides)) {
    const line = new RegExp(`^${key}=.*$`, 'm');
    text = line.test(text) ? text.replace(line, `${key}=${value}`) : `${text}\n${key}=${value}`;
  }
  writeFileSync(envFile, text);
}

async function waitForOk(url: string, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let last = 'no response';
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url, { redirect: 'manual' });
      if (res.status < 400) return;
      last = `HTTP ${res.status}`;
    } catch (err) {
      last = err instanceof Error ? err.message : String(err);
    }
    await sleep(3000);
  }
  throw new Error(`Timed out waiting for ${url} (last: ${last})`);
}

export default async function globalSetup(): Promise<void> {
  generateEnvFile();

  execFileSync(
    'docker',
    ['compose', '-p', PROJECT, '-f', 'docker-compose.yml', '--env-file', envFile, 'up', '-d'],
    { cwd: repoRoot, stdio: 'inherit' },
  );

  // Wait for the entry points behind Caddy before the browser hits them: the
  // backend API, Keycloak's realm, and the webapp itself.
  await waitForOk(`${base}/api/health`, 600_000);
  await waitForOk(`${base}/auth/realms/aisc/.well-known/openid-configuration`, 600_000);
  await waitForOk(`${base}/`, 600_000);
}
