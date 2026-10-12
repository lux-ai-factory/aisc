import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { base, buildMode, composeArgs, envFile, port, repoRoot } from './compose';

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

function compose(args: string[]): void {
  execFileSync('docker', [...composeArgs(), ...args], { cwd: repoRoot, stdio: 'inherit' });
}

/** Print the stack state and recent logs so a failure is diagnosable, not silent. */
function dumpDiagnostics(): void {
  console.error('\n[e2e] ---- docker compose ps ----');
  try {
    compose(['ps']);
  } catch {
    /* best effort */
  }
  console.error('\n[e2e] ---- docker compose logs (tail) ----');
  try {
    compose(['logs', '--no-color', '--tail', '150']);
  } catch {
    /* best effort */
  }
  console.error('[e2e] ---------------------------------\n');
}

async function isReachable(url: string): Promise<boolean> {
  try {
    const res = await fetch(url, { redirect: 'manual' });
    return res.status < 400;
  } catch {
    return false;
  }
}

async function waitForOk(label: string, url: string, timeoutMs: number): Promise<void> {
  const start = Date.now();
  const deadline = start + timeoutMs;
  let last = 'no response';
  let attempt = 0;
  while (Date.now() < deadline) {
    attempt += 1;
    try {
      const res = await fetch(url, { redirect: 'manual' });
      if (res.status < 400) {
        console.log(`[e2e] ${label} ready after ${Math.round((Date.now() - start) / 1000)}s (HTTP ${res.status})`);
        return;
      }
      last = `HTTP ${res.status}`;
    } catch (err) {
      last = err instanceof Error ? err.message : String(err);
    }
    // Progress every ~15s; the stack can take minutes on first boot.
    if (attempt % 5 === 0) {
      console.log(`[e2e] waiting for ${label} (${Math.round((Date.now() - start) / 1000)}s, last: ${last})`);
    }
    await sleep(3000);
  }
  throw new Error(`Timed out after ${timeoutMs / 1000}s waiting for ${label} at ${url} (last: ${last})`);
}

export default async function globalSetup(): Promise<void> {
  generateEnvFile();

  // In UI mode the stack is usually already up (you started it to poke at it).
  // Reuse it instead of blocking the UI on `compose up`.
  if (await isReachable(`${base}/api/openapi.json`)) {
    console.log(`[e2e] stack already running on ${base}; skipping \`compose up\``);
    return;
  }

  console.log(
    `[e2e] starting stack${buildMode ? ' (building images from source)' : ' (published images)'} on ${base}`,
  );

  try {
    const up = ['up', '-d'];
    if (buildMode) up.push('--build');
    compose(up);
  } catch (err) {
    dumpDiagnostics();
    throw err;
  }

  // Wait for the entry points behind Caddy before the browser hits them: the
  // backend API, Keycloak's realm, and the webapp itself. The backend has no
  // dedicated health route, so probe the public OpenAPI document instead — it
  // only renders once Django + Ninja are actually serving.
  try {
    await waitForOk('backend /api/openapi.json', `${base}/api/openapi.json`, 600_000);
    await waitForOk('Keycloak realm', `${base}/auth/realms/aisc/.well-known/openid-configuration`, 300_000);
    await waitForOk('webapp /', `${base}/`, 300_000);
  } catch (err) {
    dumpDiagnostics();
    throw err;
  }
}
