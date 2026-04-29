# syntax=docker/dockerfile:1
#
# PivBO container image. Server-only: no Toga, no briefcase, no GUI.
# Users hit the web UI by visiting http://localhost:5051/ on the host.
#
# Build:
#   docker build -t pivbo .
#
# Run:
#   docker run -d --name pivbo -p 5051:5051 \
#     -v pivbo-data:/home/pivbo/.local/share/PivBO \
#     ghcr.io/mbelgin/pivbo:latest
#
# The first launch downloads the historical-bars seed (~50 MB from the
# repo) into the mounted volume; subsequent runs are offline-only.

FROM python:3.12-slim

# matplotlib + reportlab need a font set for chart and PDF rendering.
# DejaVu is the standard Linux fallback and ~3 MB.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for the running app. UID 1000 is the conventional first-
# user UID on most desktop Linux hosts, so a host bind-mount (-v ./data:...)
# inherits ownership cleanly without needing chown gymnastics. A user
# can still override with `--user` at run-time if they need a different
# UID/GID for a NAS, NFS share, etc.
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin pivbo

WORKDIR /app

# Server-only deps. Toga / briefcase / GUI bits are intentionally not
# pulled in; the launcher window doesn't apply to a containerized run.
COPY requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt

# App source. The seed CSVs are NOT copied in: the first-launch seeder
# downloads them into the data volume from the repo, same as desktop.
COPY pivbo_server.py LICENSE ./
COPY pivbo/ ./pivbo/

# Listen on every interface inside the container. Without this, waitress
# binds 127.0.0.1 inside the container and rejects the connection Docker
# forwards from the host. The override only takes effect when the env
# var is set, so non-container `python pivbo_server.py` is unchanged.
ENV PIVBO_HOST=0.0.0.0

# Persistent data: simulations, prefs, drawings, seeded historical bars.
# Lives under the pivbo user's HOME so platformdirs (XDG-spec on Linux)
# resolves to /home/pivbo/.local/share/PivBO without any env override.
# Pre-create + chown so the directory exists with the right ownership
# even if no volume is mounted (named volumes inherit ownership from
# the directory they cover; bind-mounts are the user's responsibility).
RUN mkdir -p /home/pivbo/.local/share/PivBO \
    && chown -R pivbo:pivbo /home/pivbo/.local
VOLUME ["/home/pivbo/.local/share/PivBO"]

USER pivbo

EXPOSE 5051

CMD ["python", "pivbo_server.py"]
