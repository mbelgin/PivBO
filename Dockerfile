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

# Non-root, "arbitrary UID safe" image, following the OpenShift pattern
# (https://www.redhat.com/en/blog/a-guide-to-openshift-and-uids):
#
#   - Numeric default UID 1000, primary GID 0 (root group). Every
#     container run gets group 0 in its primary or supplementary set,
#     so any user-given UID can read and write the same paths as long
#     as it is in group 0 (which is the default the OpenShift scheduler
#     and most NAS panels arrange for).
#   - All writable paths under HOME are `chgrp 0 + chmod g=u`, meaning
#     the group permission bits exactly match the user's. So whoever
#     the runtime UID is, if their group set includes 0, they have full
#     access; if their UID happens to own the file on a bind-mount,
#     they have access via the user bits. Both common deployment shapes
#     (`-v named-volume:...` and `-v /host/path:...`) work without
#     image changes.
#   - HOME is set explicitly so Python's `~` expansion still resolves
#     when the runtime UID has no `/etc/passwd` entry (the case for any
#     `--user 1001` override on a NAS where the host user is 1001).
#
# Recommended overrides:
#   docker compose ... --user 1001:0           # arbitrary UID, keep GID 0
#   docker compose ... --user 1001:1001        # match host bind-mount owner
#   (No --user)                                # uses 1000:0 from the image
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

# Listen on every interface inside the container (Docker controls who
# can reach it via -p). HOME is set explicitly so platformdirs and
# Python's `~` expansion resolve correctly under any --user override,
# even if the runtime UID has no entry in /etc/passwd.
ENV PIVBO_HOST=0.0.0.0 \
    HOME=/home/pivbo

# Pre-create the data tree, hand the entire HOME to root group with
# group=user permissions. This is the OpenShift "arbitrary UID safe"
# pattern: any UID running in group 0 has full write access; any UID
# that happens to own a bind-mounted file has access via the user bits.
RUN mkdir -p /home/pivbo/.local/share/PivBO \
    && chgrp -R 0 /home/pivbo \
    && chmod -R g=u /home/pivbo
VOLUME ["/home/pivbo/.local/share/PivBO"]

USER 1000

EXPOSE 5051

CMD ["python", "pivbo_server.py"]
