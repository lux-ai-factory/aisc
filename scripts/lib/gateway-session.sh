# A signed-in browser, for checks that reach the engine. Sourced, never executed.
#
#   . scripts/lib/gateway-session.sh
#   gateway_session "$ADMIN_NAME" "$ADMIN_PASSWORD" "$jar"    # sign in at the launcher; 0 once it landed
#   through_gateway "$jar" GET /api/v1/plugins "$project"      # prints the status code
#   through_gateway "$jar" POST /api/v1/plugins "$project" '{"package_name": "x"}'
#   through_gateway_body "$jar" POST /api/v1/projects/for-platform/$project "$project" '{}'   # prints the body
#
# The engine accepts only the gateway's tokens (ENGINE_ACCEPTED_CLIENTS), so a check that wants the answer
# for a given account signs in as that account and goes through the gateway, as the browser does; a token
# of its own would be refused before the check is made.

gateway_session() { # user password jar
  # A refused password shows Keycloak's form again, with 200 too: signed in means back on the launcher.
  local launcher=${GATEWAY_LAUNCHER_URL:-http://localhost:8100/} page form landed
  page=$(curl -s -c "$3" -b "$3" -L --max-time 25 "$launcher")
  form=$(printf '%s' "$page" | grep -oE 'action="[^"]+"' | head -1 | sed 's/action="//;s/"$//' | sed 's/&amp;/\&/g')
  [ -n "$form" ] || return 1
  landed=$(curl -s -c "$3" -b "$3" -L --max-time 25 -o /dev/null -w '%{http_code} %{url_effective}' \
           --data-urlencode "username=$1" --data-urlencode "password=$2" "$form")
  case "$landed" in
    "200 $launcher"*) case "$landed" in *"/realms/"*) return 1 ;; esac ;;
    *) return 1 ;;
  esac
}

through_gateway() { # jar method path [project] [json body] -> the status code
  _gateway_curl "$1" "$2" "$3" "${4:-}" "${5:-}" -o /dev/null -w '%{http_code}'
}

through_gateway_body() { # jar method path [project] [json body] -> the body
  _gateway_curl "$1" "$2" "$3" "${4:-}" "${5:-}"
}

_gateway_curl() { # jar method path project body [more curl arguments...]; project and body may be ""
  local jar=$1 method=$2 path=$3 project=$4 body=$5
  shift 5
  set -- -s -b "$jar" -X "$method" --max-time 30 -H 'Content-Type: application/json' "$@"
  [ -n "$project" ] && set -- "$@" -H "X-AISC-Project: $project"
  [ -n "$body" ] && set -- "$@" -d "$body"
  curl "$@" "http://localhost$path"
}
