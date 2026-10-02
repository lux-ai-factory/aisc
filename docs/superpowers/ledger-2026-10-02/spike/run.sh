#!/usr/bin/env bash
# Re-runs the 2026-10-02 ledger spike on throwaway containers (network aisc-t-spike, ports 18080/18100/18088/13322).
# Never touches the running stack. Clean up: docker rm -f $(docker ps -aq -f name=aisc-t-spike-); docker network rm aisc-t-spike
set -euo pipefail
cd "$(dirname "$0")"
docker network create aisc-t-spike >/dev/null 2>&1 || true
run(){ docker run -d --name aisc-t-spike-$1 --network aisc-t-spike --network-alias $2 -e ROLE=$3 -e NAME=$1 -e PORT=$4 -v $PWD/stub.py:/stub.py:ro python:3.12-slim python -u /stub.py >/dev/null; }
run auth auth auth 4180; run platform platform platform 8000; run backend aisc-backend app 8000
run qualification qualification-web app 3000; run co control-objectives app 8090; run composer report-composer app 8095
run webapp aisc-webapp app 80; run dashboard dashboard-up app 8088
mkdir -p homepage; echo index > homepage/index.html; echo project > homepage/project.html
docker run -d --name aisc-t-spike-caddy --network aisc-t-spike --env-file caddy.env -p 127.0.0.1:18080:18080 \
  -p 127.0.0.1:18100:18100 -p 127.0.0.1:18088:18088 -v $PWD:/spike:ro -v $PWD/homepage:/srv/homepage:ro \
  caddy:2.10.2 caddy run --config /spike/${CADDYFILE:-Caddyfile.v1c} --adapter caddyfile >/dev/null
docker run -d --name aisc-t-spike-immudb --network aisc-t-spike -p 127.0.0.1:13322:3322 -e IMMUDB_ADMIN_PASSWORD=spike-admin-pw codenotary/immudb:1.11.1 >/dev/null
sleep 5
python3 probe.py 18080 POST /control-objectives/p/PID123/api/projects/a1/ratings X-AISC-Request-Id:FORGED BODY:{}
uv run --no-project --with immudb-py==1.5.0 python immu_spike.py
