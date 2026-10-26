#!/usr/bin/env bash
# Builds one wheel of shared/plugin-interface, copies it under vendor/ in the backend, the eval worker, the
# plugin-manager and each plugin repo given as an argument, and relocks each (uv lock, no --upgrade: only
# what the new wheels need moves).
#
#   scripts/vendor-plugin-interface.sh [PLUGIN_REPO ...]
#
# PyPI's latest interface (0.3.0) has no assesses, helpers or connections, and the stack's devpi is not
# reachable from a host, CI or docker build, so the locks take a wheel committed under vendor/. Each target's
# pyproject.toml must already point aisc-plugin-interface at vendor/<wheel> under [tool.uv.sources]; this
# script never edits a pyproject.
#
# A target whose [tool.uv.sources] also points aisc-plugin-manager or aisc-identity at a wheel under vendor/
# (the backend and the eval worker) gets that wheel too, built from shared/plugin-manager or shared/identity,
# so an image built from the target's Dockerfile alone holds this checkout's code.
#
# Wheels are built with SOURCE_DATE_EPOCH set to the source's last commit time, so a second run writes the
# same bytes. The script reads no secret and commits nothing.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

say() { echo "vendor-plugin-interface: $*" >&2; }
fail() { say "$*"; exit 1; }

INTERFACE=shared/plugin-interface

if [ -n "$(git -C "$INTERFACE" status --porcelain --untracked-files=no)" ]; then
  fail "$INTERFACE has uncommitted changes; the vendored wheel must be a commit's"
fi

toml_get() {  # toml_get FILE DOTTED.KEY: prints the value, or nothing when it is missing
  python3 - "$1" "$2" <<'PY'
import sys, tomllib
value = tomllib.load(open(sys.argv[1], "rb"))
for key in sys.argv[2].split("."):
    value = value.get(key) if isinstance(value, dict) else None
print("" if value is None else value)
PY
}

wheel_name() {  # wheel_name DIST VERSION
  echo "${1//-/_}-$2-py3-none-any.whl"
}

VERSION=$(toml_get "$INTERFACE/pyproject.toml" project.version)
[ -n "$VERSION" ] || fail "$INTERFACE/pyproject.toml has no project.version"
WHEEL=$(wheel_name aisc-plugin-interface "$VERSION")

TARGETS=(apps/backend apps/eval shared/plugin-manager)
for repo in "$@"; do
  [ -f "$repo/pyproject.toml" ] || fail "$repo has no pyproject.toml"
  TARGETS+=("$repo")
done

# The other local packages a target may take from vendor/: name, the folder its wheel is built from, and the
# importable package inside that folder.
LOCAL_NAMES=(aisc-plugin-manager aisc-identity)
local_folder() { case "$1" in aisc-plugin-manager) echo shared/plugin-manager ;; aisc-identity) echo shared/identity ;; esac; }
local_package() { case "$1" in aisc-plugin-manager) echo src/aisc_plugin_manager ;; aisc-identity) echo aisc_identity ;; esac; }

source_path() {  # source_path PYPROJECT DIST: the path its [tool.uv.sources] entry gives, or nothing
  python3 - "$1" "$2" <<'PY'
import sys, tomllib
sources = tomllib.load(open(sys.argv[1], "rb")).get("tool", {}).get("uv", {}).get("sources", {})
entry = sources.get(sys.argv[2])
print(entry.get("path", "") if isinstance(entry, dict) and set(entry) == {"path"} else "")
PY
}

# Check every target before writing to any.
declare -A LOCAL_WANTED=()   # "<target>|<dist>" -> 1 when the target takes that local package from vendor/
for target in "${TARGETS[@]}"; do
  if [ "$(source_path "$target/pyproject.toml" aisc-plugin-interface)" != "vendor/$WHEEL" ]; then
    fail "$target/pyproject.toml must point aisc-plugin-interface at vendor/$WHEEL under [tool.uv.sources]"
  fi
  for dist in "${LOCAL_NAMES[@]}"; do
    path=$(source_path "$target/pyproject.toml" "$dist")
    case "$path" in
      vendor/*)
        folder=$(local_folder "$dist")
        wanted=$(wheel_name "$dist" "$(toml_get "$folder/pyproject.toml" project.version)")
        [ "$path" = "vendor/$wanted" ] \
          || fail "$target/pyproject.toml must point $dist at vendor/$wanted under [tool.uv.sources]"
        if [ -n "$(git -C "$folder" status --porcelain --untracked-files=no -- "$(local_package "$dist")")" ]; then
          fail "$folder/$(local_package "$dist") has uncommitted changes; the vendored wheel must be its code as committed"
        fi
        LOCAL_WANTED["$target|$dist"]=1
        ;;
    esac
  done
done

TMP=$(mktemp -d "${TMPDIR:-/tmp}/vendor-plugin-interface.XXXXXX")
trap 'rm -rf "$TMP"' EXIT

SOURCE_DATE_EPOCH=$(git -C "$INTERFACE" log -1 --format=%ct) \
  uv build --quiet --wheel --out-dir "$TMP/interface" "$INTERFACE" >&2
[ -f "$TMP/interface/$WHEEL" ] || fail "uv build did not produce $WHEEL"

# Build each local package a target asks for, once, from a copy of its folder (setuptools writes build/ and
# egg-info next to the sources it builds).
declare -A LOCAL_WHEEL=()   # dist -> path of the built wheel
for dist in "${LOCAL_NAMES[@]}"; do
  needed=""
  for target in "${TARGETS[@]}"; do [ -n "${LOCAL_WANTED["$target|$dist"]:-}" ] && needed=1; done
  [ -n "$needed" ] || continue
  folder=$(local_folder "$dist")
  package=$(local_package "$dist")
  copy="$TMP/src-$dist"
  mkdir -p "$copy/$(dirname "$package")"
  for f in "$folder"/pyproject.toml "$folder"/README* "$folder"/LICENSE*; do
    [ -f "$f" ] && cp "$f" "$copy/"
  done
  (cd "$folder" && tar --exclude=__pycache__ --exclude='*.pyc' -cf - "$package") | (cd "$copy" && tar -xf -)
  version=$(toml_get "$folder/pyproject.toml" project.version)
  built=$(wheel_name "$dist" "$version")
  SOURCE_DATE_EPOCH=$(git -C "$folder" log -1 --format=%ct -- .) \
    uv build --quiet --wheel --out-dir "$TMP/$dist" "$copy" >&2
  [ -f "$TMP/$dist/$built" ] || fail "uv build did not produce $built"
  LOCAL_WHEEL[$dist]="$TMP/$dist/$built"
done

check_lock() {  # check_lock TARGET DIST VERSION WHEEL: the lock takes DIST VERSION from vendor/WHEEL
  python3 - "$1" "$2" "$3" "$4" <<'PY'
import hashlib, sys, tomllib
from pathlib import Path
target, dist, version, wheel = sys.argv[1:]
lock = tomllib.loads((Path(target) / "uv.lock").read_text())
entries = [p for p in lock.get("package", []) if p.get("name") == dist]
if len(entries) != 1:
    sys.exit(f"its lock has {len(entries)} packages named {dist}")
(entry,) = entries
if entry.get("version") != version:
    sys.exit(f"its lock names {dist} {entry.get('version')}, not {version}")
if entry.get("source") != {"path": f"vendor/{wheel}"}:
    sys.exit(f"its lock takes {dist} from {entry.get('source')}, not vendor/{wheel}")
digest = "sha256:" + hashlib.sha256((Path(target) / "vendor" / wheel).read_bytes()).hexdigest()
if (entry.get("wheels") or [{}])[0].get("hash") != digest:
    sys.exit(f"its lock records a hash for {dist} that is not vendor/{wheel}'s")
PY
}

for target in "${TARGETS[@]}"; do
  mkdir -p "$target/vendor"
  rm -f "$target"/vendor/aisc_plugin_interface-*.whl
  cp "$TMP/interface/$WHEEL" "$target/vendor/$WHEEL"
  for dist in "${LOCAL_NAMES[@]}"; do
    [ -n "${LOCAL_WANTED["$target|$dist"]:-}" ] || continue
    rm -f "$target"/vendor/"${dist//-/_}"-*.whl
    cp "${LOCAL_WHEEL[$dist]}" "$target/vendor/"
  done
  # --refresh-package: a rebuilt wheel keeps its file name, and uv would otherwise reuse the hash it cached
  refresh=(--refresh-package aisc-plugin-interface)
  for dist in "${LOCAL_NAMES[@]}"; do
    [ -n "${LOCAL_WANTED["$target|$dist"]:-}" ] && refresh+=(--refresh-package "$dist")
  done
  if ! out=$(cd "$target" && uv lock "${refresh[@]}" 2>&1); then
    say "$target: uv lock failed"
    echo "$out" >&2
    exit 1
  fi
  reason=$(check_lock "$target" aisc-plugin-interface "$VERSION" "$WHEEL" 2>&1) \
    || fail "$target: $reason"
  echo "vendored $WHEEL into $target; its lock names $VERSION from vendor/"
  for dist in "${LOCAL_NAMES[@]}"; do
    [ -n "${LOCAL_WANTED["$target|$dist"]:-}" ] || continue
    built=$(basename "${LOCAL_WHEEL[$dist]}")
    version=$(toml_get "$(local_folder "$dist")/pyproject.toml" project.version)
    reason=$(check_lock "$target" "$dist" "$version" "$built" 2>&1) || fail "$target: $reason"
    echo "vendored $built into $target; its lock names $version from vendor/"
  done
done
exit 0
