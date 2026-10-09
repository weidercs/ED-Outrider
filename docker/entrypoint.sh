#!/bin/sh
# The container's start: on the first run (no config yet in /config) write one for a server: every network address,
# the journals at /journals, then run Outrider with it. Settings -> Server settings edits the same file.
set -e
CONFIG=/config/ed_outrider.toml
# the folders compose mounts must be writable by this user; Docker makes a missing one owned by root (review R1): say
# what to do and wait, rather than fail and be restarted into the same failure over and over
for d in /config /app/data; do
  if ! ( touch "$d/.write-test" && rm -f "$d/.write-test" ) 2>/dev/null; then
    echo "ED Outrider cannot write $d (it runs as uid $(id -u)). On the host, in the folder with docker-compose.yml:"
    echo "  sudo chown -R $(id -u):$(id -g) docker/   then: docker compose restart"
    # wait, but stop at once when Docker asks: this script is PID 1, and PID 1 ignores SIGTERM unless it traps it
    # (an exec'd sleep never stopped, so docker stop waited out the whole stop_grace_period: found on the author's server)
    trap 'exit 0' TERM INT
    sleep infinity & wait $!
    exit 0
  fi
done
if [ ! -f "$CONFIG" ]; then
  python ed_outrider.py --config "$CONFIG" --write-config --host 0.0.0.0 --port 8025 --journals /journals >/dev/null
  echo "first run: wrote $CONFIG (host 0.0.0.0, journals /journals); set [server] password in it or in Settings"
fi
# host and port belong to the container (compose maps PORT to 8025, the health check asks 8025): pinned here, so a
# [server] host or port changed in Settings cannot make the server unreachable. Change PORT in .env instead.
exec python ed_outrider.py --config "$CONFIG" --host 0.0.0.0 --port 8025 "$@"
