#!/usr/bin/env bash
# Prepare this checkout for scripts/tests: every module environment the tests run.
#
#   scripts/prepare-tests.sh            # install them (npm ci, uv sync); rerun after pulling
#   scripts/prepare-tests.sh --check    # install nothing; list what is missing, exit 1 if anything is
#
# Works from any directory: the repository is the one this script lives in.
# Node modules get node_modules/ from their lock (npm ci); Python modules get .venv/ from their
# lock (uv sync --locked, so a lock out of date fails instead of being rewritten).
# --check looks at presence only (not freshness), needs no node, npm or uv, and makes no network call.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)

NODE_MODULES=(apps/qualification apps/controls)
UV_MODULES=(apps/backend apps/control-objectives apps/report-composer)

usage() { echo "usage: scripts/prepare-tests.sh [--check]" >&2; exit 2; }

MODE=install
case $# in
  0) ;;
  1) [ "$1" = "--check" ] || usage; MODE=check ;;
  *) usage ;;
esac

not_checked_out() { # path -> the line naming the fix
  echo "$1 is not checked out: git submodule update --init $1"
}

# every missing piece, one line each, in module order
missing() {
  local m
  for m in "${NODE_MODULES[@]}"; do
    if [ ! -f "$ROOT/$m/package.json" ]; then not_checked_out "$m"
    elif [ ! -d "$ROOT/$m/node_modules" ]; then echo "$m has no node_modules: run scripts/prepare-tests.sh"
    fi
  done
  for m in "${UV_MODULES[@]}"; do
    if [ ! -f "$ROOT/$m/pyproject.toml" ]; then not_checked_out "$m"
    elif [ ! -e "$ROOT/$m/.venv/bin/python" ]; then echo "$m has no .venv: run scripts/prepare-tests.sh"
    fi
  done
}

if [ "$MODE" = check ]; then
  lines=$(missing)
  [ -z "$lines" ] && exit 0
  printf '%s\n' "$lines"
  exit 1
fi

# install: the tools first, then every module checked out, before anything is installed
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "prepare-tests: node and npm are needed (Node.js 20) for apps/qualification and apps/controls" >&2
  exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "prepare-tests: uv is needed for apps/backend, apps/control-objectives and apps/report-composer" >&2
  exit 1
fi
for m in "${NODE_MODULES[@]}"; do
  [ -f "$ROOT/$m/package.json" ] || { echo "prepare-tests: $(not_checked_out "$m")" >&2; exit 1; }
done
for m in "${UV_MODULES[@]}"; do
  [ -f "$ROOT/$m/pyproject.toml" ] || { echo "prepare-tests: $(not_checked_out "$m")" >&2; exit 1; }
done

prepare_module() { # path command... -> runs the command in the module's folder
  local m=$1; shift
  if ! (cd "$ROOT/$m" && "$@"); then
    echo "prepare-tests: $* failed in $m" >&2
    exit 1
  fi
  echo "prepared $m"
}
for m in "${NODE_MODULES[@]}"; do prepare_module "$m" npm ci --no-audit --no-fund; done
for m in "${UV_MODULES[@]}"; do prepare_module "$m" uv sync --locked --all-extras; done
