#!/bin/sh
# Starts the MinIO server and watches its log for one known failure: a stored server config written by
# another MinIO version, holding a key this release does not know. The release then logs
# "found invalid keys (...)" and "Waiting for LDAP to be initialized" forever and never becomes healthy.
# On that pair, within the first two minutes, this script stops the server, moves
# <data>/.minio.sys/config/config.json aside (buckets, objects and IAM users are elsewhere and stay),
# says so in one line and starts the server again in its place, with the defaults. Once per container start.
#
# Every line the server prints is still shown. Any other start, or any other command, behaves as before.
# The bucket job (make_buckets) runs this image with its own entrypoint and never comes here.
set -u

WATCH_SECONDS=120

# Only `server <one data folder> ...` has a stored config to look at; anything else runs as it is.
if [ "${1:-}" != server ] || [ ! -d "${2:-}" ]; then
  exec minio "$@"
fi
stored_config="$2/.minio.sys/config/config.json"

work_dir=$(mktemp -d)
mkfifo "$work_dir/log"

# Copies the server's log to stdout. On the invalid-keys pair, writes the keys to $work_dir/invalid-keys
# and stops the server.
watch_log() {
  server_pid=$1
  started=$(date +%s)
  invalid_keys_seen=
  waiting_seen=
  while IFS= read -r line || [ -n "$line" ]; do
    printf '%s\n' "$line"
    case $line in
      *"found invalid keys ("*)
        invalid_keys_seen=1
        keys=${line#*found invalid keys (}
        keys=${keys%%)*} ;;
    esac
    case $line in *"Waiting for"*) waiting_seen=1 ;; esac
    if [ -n "$invalid_keys_seen" ] && [ -n "$waiting_seen" ] && [ -e "$stored_config" ]; then
      printf '%s' "$keys" | sed 's/[[:space:]]*$//' > "$work_dir/invalid-keys"
      kill -TERM "$server_pid" 2>/dev/null
      exec cat
    fi
    if [ $(( $(date +%s) - started )) -ge "$WATCH_SECONDS" ]; then
      exec cat
    fi
  done
}

minio "$@" > "$work_dir/log" 2>&1 &
server_pid=$!
watch_log "$server_pid" < "$work_dir/log" &
watcher_pid=$!

# docker stop sends TERM to this script (PID 1): pass it on and wait for the server to end.
stop_requested=
interrupted=
trap 'stop_requested=1; interrupted=1; kill -TERM "$server_pid" 2>/dev/null' TERM
trap 'stop_requested=1; interrupted=1; kill -INT "$server_pid" 2>/dev/null' INT
while :; do
  interrupted=
  wait "$server_pid"
  status=$?
  [ -z "$interrupted" ] && break
done
wait "$watcher_pid" 2>/dev/null

if [ -n "$stop_requested" ] || [ ! -f "$work_dir/invalid-keys" ]; then
  rm -rf "$work_dir"
  exit "$status"
fi

keys=$(cat "$work_dir/invalid-keys")
rm -rf "$work_dir"
trap - TERM INT
set_aside="$stored_config.set-aside-$(date -u +%Y%m%dT%H%M%SZ)"
if mv "$stored_config" "$set_aside"; then
  echo "minio: its stored server config was written by another MinIO version ($keys); set it aside as $set_aside and started with defaults (buckets, objects and users kept)"
else
  echo "minio: its stored server config was written by another MinIO version ($keys) and could not be moved aside from $stored_config; started as it is"
fi
exec minio "$@"
