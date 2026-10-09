import { execFileSync } from 'node:child_process';
import path from 'node:path';

const PROJECT = 'aisc-e2e';
const repoRoot = path.resolve(__dirname, '..');
const envFile = path.join(__dirname, '.env.e2e');

export default async function globalTeardown(): Promise<void> {
  try {
    execFileSync(
      'docker',
      ['compose', '-p', PROJECT, '-f', 'docker-compose.yml', '--env-file', envFile, 'down', '-v'],
      { cwd: repoRoot, stdio: 'inherit' },
    );
  } catch (err) {
    console.warn('docker compose down failed:', err);
  }
}
