import { test, expect } from '@playwright/test';

test.describe('AISC platform (published-image compose)', () => {
  test('webapp loads in a browser and renders its UI', async ({ page }) => {
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });
    page.on('pageerror', (err) => pageErrors.push(err.message));

    const response = await page.goto('/', { waitUntil: 'domcontentloaded' });
    expect(response, 'GET / returned no response').not.toBeNull();
    expect(response!.status(), 'GET / status').toBeLessThan(400);

    // A blank page means the React app never mounted (e.g. a hung auth bootstrap).
    await expect(page.locator('#root')).not.toBeEmpty({ timeout: 60_000 });
    await expect(page.getByText('AI Assessment Sandbox').first()).toBeVisible({ timeout: 60_000 });

    expect(pageErrors, `Uncaught page errors:\n${pageErrors.join('\n')}`).toEqual([]);
    const cspErrors = consoleErrors.filter((e) => /Content Security Policy|frame-ancestors/i.test(e));
    expect(cspErrors, `Content-Security-Policy errors:\n${cspErrors.join('\n')}`).toEqual([]);
  });

  test('backend API and Keycloak are reachable through the proxy', async ({ request }) => {
    const health = await request.get('/api/health');
    expect(health.ok(), `GET /api/health -> ${health.status()}`).toBeTruthy();

    const oidc = await request.get('/auth/realms/aisc/.well-known/openid-configuration');
    expect(oidc.ok(), `OIDC discovery -> ${oidc.status()}`).toBeTruthy();
  });
});
