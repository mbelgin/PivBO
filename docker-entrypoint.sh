#!/bin/sh
# Container entrypoint.
#
# Default: run as root. This is the right shape for Docker Desktop on
# Mac and Windows (the filesystem bridge translates UIDs transparently)
# and for the named-volume case on every platform.
#
# Linux users with a bind-mount who want host-side files owned by a
# specific UID can opt in with PUID and PGID env vars; the entrypoint
# then chowns /data and drops privileges via gosu.
set -e

if [ "$(id -u)" = "0" ]; then
  if [ -n "$PUID" ] || [ -n "$PGID" ]; then
    TARGET_UID="${PUID:-0}"
    TARGET_GID="${PGID:-0}"
    current_uid="$(stat -c '%u' /data 2>/dev/null || echo -1)"
    if [ "$current_uid" != "$TARGET_UID" ]; then
      chown -R "$TARGET_UID:$TARGET_GID" /data 2>/dev/null || true
    fi
    exec gosu "$TARGET_UID:$TARGET_GID" "$@"
  fi
  exec "$@"
fi

# Started with an explicit non-root UID (--user flag or `user:` in
# compose). Honor it; can't chown without root anyway.
exec "$@"
