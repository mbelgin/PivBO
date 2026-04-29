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

WORKDIR /app

# Server-only deps. Toga / briefcase / GUI bits are intentionally not
# pulled in; the launcher window doesn't apply to a containerized run.
COPY requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt

# App source. The seed CSVs are NOT copied in: the first-launch seeder
# downloads them into the data volume from the repo, same as desktop.
COPY pivbo_server.py LICENSE ./
COPY pivbo/ ./pivbo/

# Bind to 0.0.0.0 inside the container so the port Docker forwards is
# reachable. Pin the data dir to /data so platformdirs and $HOME never
# enter the picture; whatever UID can read/write /data can run the app.
ENV PIVBO_HOST=0.0.0.0 \
    PIVBO_DATA_DIR=/data

# Pre-create /data with world-writable perms so any UID picked at run
# time (named volume, bind-mount, --user override) can write into it
# on first launch. Bind-mounts always inherit the host directory's
# ownership, so this only matters when no host directory is given.
RUN mkdir -p /data && chmod 0777 /data
VOLUME ["/data"]

EXPOSE 5051

CMD ["python", "pivbo_server.py"]
