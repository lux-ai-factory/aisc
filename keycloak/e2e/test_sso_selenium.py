"""
Phase 5 — REAL Selenium proof of cross-app SSO (Single Sign-On).

All three frontends use the SAME Keycloak realm (`aisc`) with their own clients, so one login
creates a realm session that the others reuse silently. This test proves it:

  1. fresh browser -> log into the WEBAPP (creates the realm SSO session)
  2. open the QUALIFICATION app in the SAME browser -> it logs in WITHOUT asking for credentials
     again (no username/password field), landing authenticated as the same user.

Runs HEADED by default (set HEADLESS=1 to hide).
Prereqs running: Keycloak :8081, webapp dev :5173, qualification dev :3000 (any two app clients work;
swap the URLs to test other pairs — the realm session is shared across all of them).

Run:  pip install selenium && python keycloak/e2e/test_sso_selenium.py
"""
import os

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

APP_A = "http://localhost:5173/"   # webapp
APP_B = "http://localhost:3000/"   # qualification (or controls)


def make_driver():
    opts = Options()
    if os.environ.get("HEADLESS") == "1":
        opts.add_argument("--headless=new")
    for a in ("--no-sandbox", "--disable-dev-shm-usage", "--window-size=1280,900"):
        opts.add_argument(a)
    return webdriver.Chrome(options=opts)


def main() -> int:
    driver = make_driver()
    wait = WebDriverWait(driver, 25)
    try:
        # 1) log into app A (creates the realm SSO session)
        driver.get(APP_A)
        wait.until(EC.presence_of_element_located((By.ID, "username"))).send_keys("admin")
        driver.find_element(By.ID, "password").send_keys("admin")
        driver.find_element(By.ID, "kc-login").click()
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, '[data-testid="auth-username"]')))
        print("1) logged into app A as admin (realm session created)")

        # 2) open app B in the SAME browser -> silent SSO login, no credentials re-entered
        driver.get(APP_B)
        el = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, '[data-testid="auth-username"]')))
        assert el.text.strip() == "admin", f"expected admin, got '{el.text}'"
        assert "localhost:3000" in driver.current_url, f"unexpected url {driver.current_url}"
        print("2) app B logged in via SSO — NO credentials re-entered. user:", el.text)

        print("\nPASS: SSO works — one login covers multiple apps (different clients, same realm).")
        return 0
    except Exception as e:
        print("\nFAIL:", type(e).__name__, e)
        driver.save_screenshot("/tmp/sso-failure.png")
        print("screenshot: /tmp/sso-failure.png")
        return 1
    finally:
        driver.quit()


if __name__ == "__main__":
    raise SystemExit(main())
