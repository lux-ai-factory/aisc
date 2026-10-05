# Baseline before the run (taken by the orchestrator, 2026-09-24)

Repo heads:
- aisc-install feat/unified-modules 09a7cb2 (another session has uncommitted changes: Caddyfile, env.development, env.staging, scripts/secrets.sh, homepage/project.html, apps/control-objectives, apps/qualification pointers; plus earlier platform work)
- aisc-report-generator dev 26e235d
- aisc-report-plugin-interface dev 631b62b
- aisc-report-mlareject dev 2dd5649

guard-frozen.sh output at baseline (it FAILS already, because of the gateway-login work, not this run):
- G1 FAIL: engine schema differs from e34fca3 (238 lines)
- G2 PASS
- G3 PASS (hashes), G3 PASS (tests/test_vendored.py)
- G4 FAIL: Sean's files differ: aisc_backend/routers/plugin.py config/settings.py pyproject.toml
- G4 FAIL: files outside the allowed set differ: admin.py, 0024_no_login_of_its_own.py, routers/plugin.py, config/jwt.py, config/settings.py, config/urls.py
- G4 FAIL: Dockerfile differs by more than dfe4120
- G5 PASS
The end state must show exactly the same lines (no new FAIL, nothing new in G1's diff line count).

Known pre-existing test failures (from the report run of 2026-09-23, 05-report.md section 2):
- aisc-report-generator 218/220 (test_r2_2_2_tags contradicts the spec; test_service get json={} TypeError)
- apps/report-composer 99/107 (8 test-helper defects: Throwaway.rows() footer parsing, TestClient.get json=None)
- interface 45 passed, mlareject 19 passed
Stage 2 re-measures these before writing any test and records the numbers in 02-tests.md.
