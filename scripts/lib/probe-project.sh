# The project a check run acts in. Sourced, never executed (the caller has sourced stack-name.sh).
#
#   . scripts/lib/probe-project.sh
#   probe_project_for "$TOKEN"   # sets PROBE_PID: the account's first project, or the probe made for it
#
# probe_project_for sets variables, so call it directly, not inside $(...).
#
# The checks act as an ordinary account inside one of its projects. A fresh install has none, so the
# first run makes "verify probe" as that account (which makes it the owner), and every later run finds it
# as the account's project. It is never deleted: a project keeps its ledger database for good, deleted or
# not, so a probe made and deleted per run would use up the ledger pool.

PROBE_NAME="verify probe"
PROBE_PID=""

_platform() { # method path token [json body]
  docker exec -e M="$1" -e P="$2" -e T="$3" -e B="${4:-}" "$(aisc_container platform)" python -c '
import os, sys, urllib.request
body = os.environ["B"].encode() or None
req = urllib.request.Request("http://localhost:8000" + os.environ["P"], data=body, method=os.environ["M"],
    headers={"Authorization": "Bearer " + os.environ["T"], "Content-Type": "application/json"})
try:
    print(urllib.request.urlopen(req, timeout=60).read().decode())
except urllib.error.HTTPError as e:
    print(e.read().decode(), file=sys.stderr); sys.exit(1)
' 2>/dev/null
}

probe_project_for() { # token
  PROBE_PID=$(_platform GET /projects "$1" | python3 -c 'import json,sys; p=json.load(sys.stdin); print(p[0]["pid"] if p else "")' 2>/dev/null)
  if [ -z "$PROBE_PID" ]; then
    PROBE_PID=$(_platform POST /projects "$1" "{\"name\": \"$PROBE_NAME\"}" \
                | python3 -c 'import json,sys; print(json.load(sys.stdin)["pid"])' 2>/dev/null)
  fi
}
