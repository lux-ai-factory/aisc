import path from 'node:path';

export const PROJECT = 'aisc-e2e';
export const repoRoot = path.resolve(__dirname, '..');
export const envFile = path.join(__dirname, '.env.e2e');
export const port = process.env.E2E_PORT ?? '8080';
export const base = `http://localhost:${port}`;

/**
 * E2E_BUILD=1 runs the stack from images built from the checked-out submodules
 * (docker-compose.build.yml) instead of pulling the published GHCR images.
 * global-setup and global-teardown must agree on the file list.
 */
export const buildMode = process.env.E2E_BUILD === '1';

export function composeArgs(): string[] {
  const args = ['compose', '-p', PROJECT, '-f', 'docker-compose.yml'];
  if (buildMode) args.push('-f', 'docker-compose.build.yml');
  args.push('--env-file', envFile);
  return args;
}
