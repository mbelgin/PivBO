#!/bin/sh
# Container entrypoint: runs as root, ensures /data is writable by the
# target UID, then drops privileges via gosu and execs the server.
# Solves the bind-mount-plus-non-root-UID problem without requiring
# users to chown anything on the host.
set -e

TARGET_UID="${PUID:-1000}"
TARGET_GID="${PGID:-1000}"

if [ "$(id -u)" = "0" ]; then
  # Only chown if ownership doesn't already match. Skips a recursive
  # walk on every restart for users with a populated /data tree.
  current_uid="$(stat -c '%u' /data 2>/dev/null || echo -1)"
  if [ "$current_uid" != "$TARGET_UID" ]; then
    chown -R "$TARGET_UID:$TARGET_GID" /data 2>/dev/null || true
  fi
  exec gosu "$TARGET_UID:$TARGET_GID" "$@"
fi

# Already non-root (someone passed --user to docker run / `user:` in
# compose). Honor that, skip the chown attempt (would fail anyway).
exec "$@"
