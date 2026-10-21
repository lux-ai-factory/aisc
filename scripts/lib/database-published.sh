# Sourced by the checks that read the stack's Postgres from the host (PGHOST and PGPORT set). A default install
# does not publish it (docker-compose.admin-ports.yml does, when asked), and a connection error would not say
# why: so when nothing answers there, this says how to publish it and stops the check with a failure.
# bash's /dev/tcp, so the host needs no psql or nc. A Unix socket folder (PGHOST=/...) is not probed.
case "$PGHOST" in
  /*) ;;
  *)
    if ! (exec 3<>"/dev/tcp/$PGHOST/$PGPORT") 2>/dev/null; then
      echo "Nothing answers on $PGHOST:$PGPORT, so the database is not published on this machine: set" \
           "AISC_ADMIN_PORTS=on (in the environment or env.local) and run start, then run this again." >&2
      exit 1
    fi ;;
esac
