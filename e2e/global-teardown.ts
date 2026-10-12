import { execFileSync } from 'node:child_process';
import { base, composeArgs, repoRoot } from './compose';

export default async function globalTeardown(): Promise<void> {
  // E2E_KEEP=1 leaves the stack up so you can open the webapp yourself.
  if (process.env.E2E_KEEP === '1') {
    console.log(`\n[e2e] E2E_KEEP=1 — stack left running at ${base}`);
    console.log(`[e2e] tear it down with: docker ${composeArgs().join(' ')} down -v\n`);
    return;
  }

  try {
    execFileSync('docker', [...composeArgs(), 'down', '-v'], { cwd: repoRoot, stdio: 'inherit' });
  } catch (err) {
    console.warn('docker compose down failed:', err);
  }
}
