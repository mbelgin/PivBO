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

# Default user UID 1000 with primary GID 0 so writable paths can be
# group-owned by 0 (see chgrp/chmod below). This is what makes the image
# safe to run under an arbitrary `--user` override without rebuilding.
RUN useradd --create-home --uid 1000 --gid 0 --shell /usr/sbin/nologin pivbo

WORKDIR /app

# Server-only deps. Toga / briefcase / GUI bits are intentionally not
# pulled in; the launcher window doesn't apply to a containerized run.
COPY requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt

# App source. The seed CSVs are NOT copied in: the first-launch seeder
# downloads them into the data volume from the repo, same as desktop.
COPY pivbo_server.py LICENSE ./
COPY pivbo/ ./pivbo/

# PIVBO_HOST: container internals bind to 0.0.0.0 so the port Docker
# forwards is reachable. HOME: explicit so Python's `~` expansion (and
# hence platformdirs) still resolves when the runtime UID has no entry
# in /etc/passwd.
ENV PIVBO_HOST=0.0.0.0 \
    HOME=/home/pivbo

# Make the writable tree group-0 owned with group permissions matching
# user permissions. With `useradd --gid 0` above, the default user
# already has the right access; an arbitrary --user override gets the
# same access by either being in group 0 or owning the path on a
# bind-mount.
RUN mkdir -p /home/pivbo/.local/share/PivBO \
    && chgrp -R 0 /home/pivbo \
    && chmod -R g=u /home/pivbo
VOLUME ["/home/pivbo/.local/share/PivBO"]

USER 1000

EXPOSE 5051

CMD ["python", "pivbo_server.py"]
