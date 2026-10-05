#!/usr/bin/env bash
# The secrets this install runs on, generated here and never committed.
#
#   ./scripts/secrets.sh            # make them if they are missing
#   ./scripts/secrets.sh --rotate   # make new ones, replacing what is there
#   ./scripts/secrets.sh --add-ledger-key   # add the next version of the ledger's master key
#
# A secret committed to the repo is a secret every clone shares. The worst of
# them would be the gateway's cookie secret: whoever holds it can mint a
# session cookie for any user, offline, and that cookie is the session every
# module trusts.
#
# So none of them has a default. The compose files refuse to start without
# these, this writes them once into env.secrets, which is git-ignored, and the
# realm import is rendered from its template with the same values.
#
# PLATFORM_SECRETS_KEY is the exception to --rotate: it encrypts the LLM API keys
# stored in every project's database, so a fresh one would make all of them
# unreadable. --rotate keeps it. To rotate it: prepend a new Fernet key to it
# (comma list, newest first), restart the platform, run
#   python -m platform_service.llm_store rotate
# in the platform container, then drop the old key from the list.
#
# The ledger's two secrets survive --rotate too:
# - PLATFORM_LEDGER_KEYS is versioned ("v1:<hex>,v2:<hex>") and every version is kept for ever,
#   because the digests in immudb were made with them. Rotating means adding the next version
#   (--add-ledger-key) and restarting the platform; new digests use it, old ones still check.
# - LEDGER_IMMUDB_PASSWORD is the platform's immudb user's (aisc_ledger); it changes only together
#   with immudb's own copy, through scripts/ledger-pool.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
# Every file written here holds secrets or is made from them: private from the moment it exists,
# not only after the chmod further down.
umask 077

OUT=env.secrets
COMBINED=env.runtime   # what compose is pointed at: the settings plus the secrets
TEMPLATE=keycloak/aisc-realm.json
RENDERED=keycloak/aisc-realm.local.json

rand()      { openssl rand -hex 32; }
# oauth2-proxy decodes this as base64url and wants exactly 32 bytes out. With
# padding it does not decode, and it then measures the string itself and
# refuses to start: "cookie_secret must be 16, 24, or 32 bytes ... but is 44".
cookie()    { openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\n'; }
# Fernet wants urlsafe base64 of 32 bytes WITH its `=` padding: 44 characters.
fernet()    { openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'; }
# The ledger's master key list starts at version 1.
ledgerkey() { local k; k=$(rand) && echo "v1:$k"; }
# immudb refuses a password without an upper and a lower case letter, a digit and a symbol, or over 32
# characters: 24 random hex (96 bits) behind a fixed prefix that has one of each.
immudbpw()  { local k; k=$(openssl rand -hex 12) && echo "Az9-$k"; }

# Every secret, in the order a new env.secrets lists them, as NAME=kind of value it takes.
# A secret added here reaches existing installs too: the loop below appends whatever an
# env.secrets lacks, never replacing a value that is there.
SECRETS=(
GATEWAY_COOKIE_SECRET=cookie
GATEWAY_CLIENT_SECRET=rand
CATALOGUE_INSTALL_TOKEN=rand
DJANGO_SECRET_KEY=rand
INTERNAL_API_KEY=rand
SUPERSET_SECRET_KEY=rand
# signs the dashboard's guest tokens (embedding is on): never Superset's published default
SUPERSET_GUEST_TOKEN_SECRET=rand
DASHBOARD_ADMIN_PASSWORD=rand
# the platform's calls to the dashboard's bridge (/api/v1/aisc_project); with none, it refuses them all
DASHBOARD_BRIDGE_TOKEN=rand
REPORT_SERVICE_TOKEN=rand
REPORT_RO_PASSWORD=rand
REPORT_COMPOSER_PASSWORD=rand
INSPECTOR_PASSWORD=rand
# One token per agentic system, so each agent resolves only its own choice and key.
PLATFORM_CARD_AGENT_TOKEN=rand
PLATFORM_RISK_MAPPER_TOKEN=rand
# the plugin-side client of Manage -> Connections resolves a connection with it (platform, eval worker)
PLATFORM_CONNECTIONS_TOKEN=rand
# One token per caller edge of the service-only APIs: each
# is held by its caller and its callee only, so no service can call another with
# a token it was not given.
QUALIFICATION_AGENTS_TO_WEB_TOKEN=rand
QUALIFICATION_WEB_TO_AGENTS_TOKEN=rand
QUALIFICATION_WEB_TO_ONTOLOGY_TOKEN=rand
QUALIFICATION_AGENTS_TO_ONTOLOGY_TOKEN=rand
QUALIFICATION_WEB_TO_PREFILL_TOKEN=rand
QUALIFICATION_WEB_TO_PDF_TOKEN=rand
CONTROLS_WEB_TO_PDF_TOKEN=rand
PLATFORM_SECRETS_KEY=fernet
# immudb's superuser: compose starts immudb with IMMUDB_FORCE_ADMIN_PASSWORD, so a new value is applied
# at its next start
IMMUDB_ADMIN_PASSWORD=immudbpw
# the ledger: the platform's immudb user, and its versioned master keys (both kept by --rotate)
LEDGER_IMMUDB_PASSWORD=immudbpw
PLATFORM_LEDGER_KEYS=ledgerkey
# platform_rw, the platform service's database role: postgres-setup applies it on every start
PLATFORM_RW_PASSWORD=rand
# qualification_rw, the qualification app's database role: postgres-setup applies it on every start
QUALIFICATION_RW_PASSWORD=rand
# control_objectives_rw, the control objectives service's database role: postgres-setup applies it
CONTROL_OBJECTIVES_RW_PASSWORD=rand
# dashboard_ro, the results dashboard's read role: postgres-setup applies it
DASHBOARD_RO_PASSWORD=rand
# the ledger witness: Caddy sends it, the platform checks it
AISC_WITNESS_GATEWAY_SECRET=rand
# one token per caller that posts ledger events, held by it and the platform only
PLATFORM_LEDGER_ENGINE_TOKEN=rand
PLATFORM_LEDGER_DASHBOARD_TOKEN=rand
PLATFORM_LEDGER_AGENTS_TOKEN=rand
)
value_of() { case "$1" in cookie) cookie ;; fernet) fernet ;; ledgerkey) ledgerkey ;; immudbpw) immudbpw ;; *) rand ;; esac; }
# What --rotate keeps: replacing any of these would make stored data unreadable or unverifiable.
KEPT_ON_ROTATE=" PLATFORM_SECRETS_KEY LEDGER_IMMUDB_PASSWORD PLATFORM_LEDGER_KEYS "

# A value of NAME in a file: empty when the line is missing or has no value.
value_in() { awk -v n="$1" 'index($0, n "=") == 1 { print substr($0, length(n) + 2); exit }' "$2"; }
# A new value, or empty when openssl failed (set -e would otherwise stop without a word).
fresh()    { value_of "$1" || true; }

# What survives --rotate (see the top of this file), read before anything is written.
declare -A kept=()
if [ -f "$OUT" ]; then
  for name in $KEPT_ON_ROTATE; do kept[$name]=$(value_in "$name" "$OUT"); done
fi

# --add-ledger-key: the next version of the ledger's master key, appended; nothing else changes. It
# then goes on as a plain run (values kept), so env.runtime carries the new version too.
if [ "${1:-}" = "--add-ledger-key" ]; then
  [ -f "$OUT" ] || { echo "$OUT does not exist: run scripts/secrets.sh first" >&2; exit 1; }
  current=$(value_in PLATFORM_LEDGER_KEYS "$OUT")
  [ -n "$current" ] || { echo "PLATFORM_LEDGER_KEYS is missing from $OUT: run scripts/secrets.sh first" >&2; exit 1; }
  if ! [[ "$current" =~ ^v[1-9][0-9]*:[0-9a-f]{64}(,v[1-9][0-9]*:[0-9a-f]{64})*$ ]]; then
    echo "PLATFORM_LEDGER_KEYS in $OUT is not v<N>:<64 hex>[,...]: fix it by hand; nothing changed" >&2
    exit 1
  fi
  next=$(( $(tr ',' '\n' <<<"$current" | sed -n 's/^v\([0-9]*\):.*/\1/p' | sort -n | tail -1) + 1 ))
  key=$(rand) || { echo "openssl failed; $OUT left as it was" >&2; exit 1; }
  tmp=$(mktemp "$OUT.XXXXXX")
  trap 'rm -f "$tmp"' EXIT
  NAME=PLATFORM_LEDGER_KEYS VALUE="$current,v$next:$key" awk 'index($0, ENVIRON["NAME"] "=") == 1 { print ENVIRON["NAME"] "=" ENVIRON["VALUE"]; next } { print }' "$OUT" > "$tmp"
  mv "$tmp" "$OUT"
  trap - EXIT
  echo "added ledger key version v$next to $OUT (the platform reads it once its compose passes PLATFORM_LEDGER_KEYS, from phase 3)"
  set --
fi

# The new env.secrets is built beside the old one and moved into place at the end, so a run that
# fails (openssl, a full disk) leaves the old file as it was.
tmp=$(mktemp "$OUT.XXXXXX")
trap 'rm -f "$tmp" "$tmp.next"' EXIT

if [ "${1:-}" = "--rotate" ] || [ ! -f "$OUT" ]; then
  {
    echo "# Generated by scripts/secrets.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ). Not in git."
    echo "# Rotating these signs everyone out and needs Keycloak re-imported (make clean)."
    for entry in "${SECRETS[@]}"; do
      name=${entry%%=*}
      if [[ "$KEPT_ON_ROTATE" == *" $name "* ]] && [ -n "${kept[$name]:-}" ]; then
        echo "$name=${kept[$name]}"
      else
        echo "$name=$(fresh "${entry#*=}")"
      fi
    done
  } > "$tmp"
  made="${#SECRETS[@]} secrets, $( [ "${1:-}" = "--rotate" ] && echo rotated || echo new )"
else
  echo "$OUT exists; keeping its values and adding any that are missing (--rotate to replace)"
  cat "$OUT" > "$tmp"
  # an append must start on a line of its own
  if [ -s "$tmp" ] && [ -n "$(tail -c1 "$tmp")" ]; then echo >> "$tmp"; fi
  for entry in "${SECRETS[@]}"; do
    name=${entry%%=*}
    if ! grep -q "^$name=" "$tmp"; then
      echo "$name=$(fresh "${entry#*=}")" >> "$tmp"
      echo "added $name to $OUT"
    fi
  done
  made="kept, missing ones added"
fi

# An empty value is a missing one (openssl failed now, or an earlier run left NAME=): made again
# in its place, and if it is still empty nothing is written.
for entry in "${SECRETS[@]}"; do
  name=${entry%%=*}
  if [ -z "$(value_in "$name" "$tmp")" ]; then
    value=$(fresh "${entry#*=}")
    if [ -z "$value" ]; then
      echo "$name is empty and could not be generated (does openssl work?); $OUT left as it was" >&2
      exit 1
    fi
    NAME="$name" VALUE="$value" awk 'index($0, ENVIRON["NAME"] "=") == 1 && !done { print ENVIRON["NAME"] "=" ENVIRON["VALUE"]; done = 1; next } { print }' "$tmp" > "$tmp.next"
    mv "$tmp.next" "$tmp"
    echo "generated the empty $name again"
  fi
done
mv "$tmp" "$OUT"
trap - EXIT
echo "wrote $OUT ($made)"

# The one with a shape requirement, checked here rather than discovered by a
# gateway that will not start.
cookie_len=$(awk -F= '/^GATEWAY_COOKIE_SECRET=/{print length($2)}' "$OUT")
if [ "$cookie_len" != "43" ]; then
  echo "GATEWAY_COOKIE_SECRET is $cookie_len characters; oauth2-proxy needs 32 bytes base64url (43)" >&2
  exit 1
fi

# The realm import carries two of them. Rendered, never committed: the template
# holds placeholders so the repo itself has no secret in it.
# shellcheck disable=SC1090
set -a; . "./$OUT"; set +a
python3 - "$TEMPLATE" "$RENDERED" <<'PY'
import os, sys
template, rendered = sys.argv[1], sys.argv[2]
text = open(template, encoding="utf-8").read()
for name in ("GATEWAY_CLIENT_SECRET",):
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"{name} is not set: run scripts/secrets.sh first")
    text = text.replace("__%s__" % name, value)
open(rendered, "w", encoding="utf-8").write(text)
print(f"rendered {rendered} from {template}")
PY
# It holds a client secret, so it stays unreadable to others, except to Keycloak, which runs as
# uid 1000 in its container and reads it at import (without this it fails: Permission denied).
chmod 600 "$RENDERED"
if command -v setfacl >/dev/null 2>&1; then
  setfacl -m u:1000:r "$RENDERED"
else
  echo "setfacl is missing: let uid 1000 (Keycloak) read $RENDERED, or Keycloak will not start" >&2
fi

# immudb signs its states with this key; the platform checks them with the public
# half. Made once and never replaced, --rotate included: a new key would make every saved state
# unverifiable. Private to this user, readable by immudb's uid 3322 only.
SIGNING_KEY=immudb-signing.key
SIGNING_PUB=immudb-signing.pub
if [ ! -s "$SIGNING_KEY" ]; then
  openssl ecparam -name prime256v1 -genkey -noout -out "$SIGNING_KEY.new" 2>/dev/null \
    && openssl ec -in "$SIGNING_KEY.new" -pubout -out "$SIGNING_PUB" 2>/dev/null \
    || { rm -f "$SIGNING_KEY.new"; echo "openssl could not make $SIGNING_KEY" >&2; exit 1; }
  mv "$SIGNING_KEY.new" "$SIGNING_KEY"
  echo "made $SIGNING_KEY and $SIGNING_PUB"
fi
chmod 600 "$SIGNING_KEY"
chmod 644 "$SIGNING_PUB"
if command -v setfacl >/dev/null 2>&1; then
  setfacl -m u:3322:r "$SIGNING_KEY"
else
  echo "setfacl is missing: let uid 3322 (immudb) read $SIGNING_KEY, or immudb will not start" >&2
fi

# compose takes one --env-file, so the settings and the secrets are combined
# into one. Also git-ignored, also regenerated from its two sources.
: > "$COMBINED"
cat env.plugin_downloader "$OUT" >> "$COMBINED"
chmod 600 "$COMBINED"
echo "wrote $COMBINED (env.plugin_downloader + $OUT)"
echo
echo "run the stack with:"
echo "  docker compose -p aisc --env-file $COMBINED -f docker-compose.plugin_downloader.yml \\"
echo "    -f docker-compose-infra.development.yml -f docker-compose.development.yml up -d"
