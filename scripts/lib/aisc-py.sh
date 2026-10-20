# Sourced by the install scripts: runs scripts/aisc.py with uv, which brings Python and its one library.
aisc_py() {
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv is needed to install AISC: https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
  fi
  exec uv run --quiet --script scripts/aisc.py "$@"
}
