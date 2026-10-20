# The realm's two development accounts and their passwords. Sourced, never executed.
#
#   . scripts/lib/dev-accounts.sh
#   gateway_session "$ADMIN_NAME" "$ADMIN_PASSWORD" "$jar"
#
# The passwords are generated into env.secrets (scripts/secrets.sh) and put into the realm at import.
# VERIFY_ADMIN_USER / VERIFY_ADMIN_PASSWORD and VERIFY_USER / VERIFY_PASSWORD, when set, name other
# accounts. Exported, so a check's Python part reads the same ones.

_secret_value() { # NAME -> its value in env.secrets, or nothing
  awk -v n="$1" 'index($0, n "=") == 1 { print substr($0, length(n) + 2); exit }' \
    "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/env.secrets" 2>/dev/null
}

export VERIFY_ADMIN_USER=${VERIFY_ADMIN_USER:-admin}
export VERIFY_ADMIN_PASSWORD=${VERIFY_ADMIN_PASSWORD:-$(_secret_value AISC_ADMIN_PASSWORD)}
export VERIFY_USER=${VERIFY_USER:-user}
export VERIFY_PASSWORD=${VERIFY_PASSWORD:-$(_secret_value AISC_USER_PASSWORD)}
ADMIN_NAME=$VERIFY_ADMIN_USER; ADMIN_PASSWORD=$VERIFY_ADMIN_PASSWORD
USER_NAME=$VERIFY_USER; USER_PASSWORD=$VERIFY_PASSWORD
if [ -z "$ADMIN_PASSWORD" ] || [ -z "$USER_PASSWORD" ]; then
  echo "the development accounts' passwords are missing from env.secrets: run scripts/secrets.sh" >&2
fi
