# PivBO — Developer Guide

Covers pulling source, running in dev, packaging, releasing, and a
quick tour of the moving parts. If you're a user wanting to try the
app, start with `README.md` instead — it has download links and
install instructions.

## Prerequisites

- **Python 3.11 or 3.12** (3.13 may work; Briefcase lags a version)
- **Git**
- **Platform-specific, only when building installers for that platform:**
  - Windows: [WiX Toolset v3](https://github.com/wixtoolset/wix3/releases) on `PATH` (Briefcase auto-installs it on first run if missing)
  - macOS: Xcode command line tools (`xcode-select --install`)
  - Linux AppImage build: Docker installed and running (Briefcase uses a containerized build for AppImage portability)

## Clone + run in dev

```bash
git clone git@github.com:mbelgin/PivBO.git
cd PivBO
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate
pip install -r requirements.txt
python pivbo_server.py
```

Server listens on `http://localhost:5051/`. Open in a browser.

Dev mode is detected by the presence of `pyproject.toml` next to
`pivbo_server.py`. When that's true, `USER_DATA_DIR == SCRIPT_DIR`, so
the repo's `collected_stocks/` and `simulations/` folders are used
directly. No seeder runs because files already exist.

To simulate installed-mode paths locally:

```bash
PIVBO_FORCE_USER_DATA_DIR=1 python pivbo_server.py   # macOS/Linux
$env:PIVBO_FORCE_USER_DATA_DIR='1'; python .\pivbo_server.py   # PowerShell
```

This forces `platformdirs.user_data_dir(...)` to resolve the same paths
end users see (e.g. `%APPDATA%\PivBO\`), useful for debugging
first-launch seeding and migrations.

## Repo layout

```
pivbo/                          # Python package (everything bundled into installers)
  __init__.py
  __main__.py                   # Entry point — the installed app launches here
  launcher.py                   # Toga control window (Start/Stop/Port/Open browser)
  pivbo.html                    # Single-page web UI (chart, sim, duel, prefs)
  collected_stocks_manifest.txt # Ticker list consumed by the first-launch seeder
  assets/                       # Icons, favicon
pivbo_server.py                 # Flask server — serves pivbo.html + /api/*
collected_stocks/               # 931 historical .csv.gz files (repo-tracked seed data,
                                # NOT bundled into the installer — fetched by seeder
                                # from raw.githubusercontent.com on first launch)
simulations/ templates/ analyses/   # Per-user runtime data (gitignored)
pyproject.toml                  # Briefcase config (project_name, icon, deps, per-OS)
requirements.txt                # Dev-time dependencies
.github/workflows/release.yml   # Tag-triggered CI that builds all three OS artifacts
```

## Architecture cheat sheet

- **Backend**: single Flask app in `pivbo_server.py`, served by
  [waitress](https://pypi.org/project/waitress/) (pure-Python WSGI,
  cross-platform). Flask's built-in dev server is not used in either
  dev or packaged mode — waitress is both faster and silent about the
  usual "do not use in production" warning. All state (simulations,
  templates, analyses, preferences) is per-user JSON under
  `USER_DATA_DIR`. No database. Thread pool size is derived from
  `os.cpu_count()` at startup so a small laptop and a workstation
  both get a sensible default.
- **Frontend**: single `pivbo.html` (~380KB of inline CSS/JS) served as
  a static file. Chart panes use [lightweight-charts](https://github.com/tradingview/lightweight-charts); the equity pane is hand-rolled Canvas.
- **Launcher**: [Toga](https://toga.readthedocs.io/) desktop window that
  owns the Flask-server thread. Lets the user Start/Stop/Quit cleanly
  and hosts the "Open in browser" shortcut.
- **Duel Mode**: 1v1 over the public HiveMQ MQTT broker
  (`wss://broker.hivemq.com:8884/mqtt`). Room codes scope the traffic;
  clients use `mqtt.js` from a CDN. Full protocol notes were in the
  (now-private) `duel_mode_handover.md`.
- **First-launch seeder**: `pivbo_server.py :: _seed_run()`. On startup a
  daemon thread iterates `collected_stocks_manifest.txt` and pulls any
  missing `.csv.gz` from `raw.githubusercontent.com/mbelgin/PivBO/main/collected_stocks/<TICKER>.csv.gz`
  into `USER_DATA_DIR/collected_stocks/`. Existence-only check — never
  overwrites an existing file, so a user's own wider-range downloads
  survive re-runs. `/api/seed/status` drives the UI banner.

## Building installers

All three OSes use Briefcase. You can only build for the OS you're
running on. The release workflow handles all three automatically on
tag push; locally you typically only build for your own platform.

### Windows (portable ZIP, what users download)

```powershell
briefcase update windows
briefcase build windows
# Portable distribution: zip the staged folder.
Compress-Archive -Path build\pivbo\windows\app\src\* -DestinationPath dist\PivBO-windows.zip -Force
```

Produces `dist\PivBO-windows.zip`. Extracting and running `PivBO.exe`
inside is the end-user flow.

If a running `PivBO.exe` holds a file lock during `briefcase build`,
kill it:

```powershell
Get-Process -Name "PivBO*" -ErrorAction SilentlyContinue | Stop-Process -Force
```

We do not ship an MSI. Portable ZIP is the only Windows artifact.
Skip `briefcase package windows` entirely.

### macOS (zipped .app)

```bash
briefcase update macOS
briefcase build macOS
ditto -c -k --keepParent build/pivbo/macos/app/PivBO.app dist/PivBO-macos.zip
```

`ditto` preserves the bundle's extended attributes, which a plain `zip`
strips (breaks Gatekeeper's ad-hoc signature).

`universal_build = true` in `pyproject.toml` makes the .app run on both
Intel and Apple Silicon.

### Linux (AppImage)

```bash
briefcase update linux AppImage
briefcase build linux AppImage
briefcase package linux AppImage
```

Output: `dist/PivBO-<version>-x86_64.AppImage`. AppImage requires Docker
on the host — Briefcase runs the build inside a containerized Ubuntu
22.04 so the glibc baseline stays broad.

## Release workflow

The git tag is the version source of truth. CI reads `github.ref_name`
(e.g. `v0.0.2`), strips the leading `v`, and writes the version into
BOTH `pyproject.toml` and `pivbo/__init__.py` via `scripts/pin_version.py`
before briefcase runs. So locally you don't need to bump anything — just
tag and push.

```bash
# Optional: regenerate the ticker manifest if collected_stocks/ changed.
python scripts/pin_version.py            # shows current version, no changes

# Optional: bump the committed version so dev-mode `/api/version`
# reflects what's coming next. CI doesn't care what's committed — it
# uses the tag — so this is cosmetic for dev-mode users only.
python scripts/pin_version.py 0.0.2

git commit -am "Bump version to 0.0.2"   # only if you ran pin_version

# The actual release:
git tag v0.0.2
git push && git push --tags
```

CI runs the matrix build (`.github/workflows/release.yml`). Three
artifacts land on the Release page with the tag's version baked in:
- `PivBO-windows.zip`
- `PivBO-macos.zip`
- `PivBO-x86_64.AppImage`

(If wired) winget and Homebrew tap manifests auto-bump from the same
workflow — see the workflow file for details.

### Regenerating the ticker manifest

Only needed when you add or remove `.csv.gz` files in `collected_stocks/`:

```bash
python -c "import os; names = sorted(n[:-7].upper() for n in os.listdir('collected_stocks') if n.lower().endswith('.csv.gz')); open('pivbo/collected_stocks_manifest.txt','w',encoding='utf-8',newline='\n').writelines(n+'\n' for n in names)"
```

### Version source of truth

`pivbo/__init__.py` defines `__version__`. `pivbo_server.py` imports it.
The landing page reads `/api/version` at runtime, so the about / footer
line updates without code changes once the server has the right version.
`pyproject.toml`'s `version` field must match — `scripts/pin_version.py`
keeps them in sync with one command.

## Package manager integrations

### Winget (Windows)

- Manifest lives upstream in `microsoft/winget-pkgs`.
- Bump automation uses [Komac](https://github.com/russellbanks/Komac)
  from the release workflow. It reads the new GitHub release asset, hashes
  it, writes the YAML, opens a PR.
- Secret needed: `WINGET_TOKEN` (fine-grained PAT scoped to your fork of
  `winget-pkgs`).

### Homebrew Cask (macOS)

- Own tap: `github.com/mbelgin/homebrew-pivbo`. Users install with:
  ```bash
  brew tap mbelgin/pivbo
  brew install --cask pivbo
  ```
- Cask file `Casks/pivbo.rb` updated by the release workflow after each
  tag: new version, new SHA256, commit to the tap repo.
- Secret needed: `HOMEBREW_TAP_TOKEN` (PAT with write access to the tap
  repo).

### AppImage (Linux)

- No package manager integration by default. Users download from the
  GitHub release.
- Optional: submit to [AppImageHub](https://appimage.github.io/) for
  discoverability. One-time YAML PR, not per-release.

## Common dev tasks

**Validate HTML/JS syntax before committing:**

```bash
node -e "
const fs = require('fs');
const s = fs.readFileSync('pivbo/pivbo.html', 'utf8');
const m = s.match(/<script>([\s\S]*?)<\/script>/g);
m.forEach((b, i) => {
  const code = b.replace(/^<script>/, '').replace(/<\/script>$/, '');
  try { new Function(code); console.log('block', i, 'OK'); }
  catch(e) { console.log('block', i, 'ERR:', e.message); }
});
"
```

**Python syntax check:**

```bash
python -m py_compile pivbo_server.py pivbo/launcher.py
```

**Smoke-test the seeder state endpoint locally:**

```bash
curl http://localhost:5051/api/seed/status
```

**Invalidate the ticker-ranges cache** (if CSVs were swapped in a running
server): restart. The seeder's completion hook already flips the cache
flag; direct-edits to files outside the seeder's knowledge aren't picked
up until a restart.

## Gotchas

- **Adding / bumping a dependency**: `briefcase update <platform>` does
  NOT re-resolve the `requires` list in `pyproject.toml` by default —
  it only copies source-tree changes. If you add or bump a dep there
  (for example when we switched from werkzeug to waitress) the next
  build will crash with `ModuleNotFoundError` inside the packaged
  app. Fix it with either:
  ```bash
  briefcase update <platform> -r     # -r == --update-requirements
  # OR
  rm -rf build/ && briefcase create <platform>
  ```
  The full `briefcase create` path is slower but always correct; `-r`
  works when you remember to pass it.
- **Briefcase stub lock on Windows**: `briefcase build windows` edits
  `PivBO.exe` via `rcedit`. If the exe is running, it fails with
  "Unable to update details on stub app." Kill the process, retry.
- **macOS `ditto` vs `zip`**: always `ditto -c -k --keepParent`. A
  regular `zip` loses the code-signing extended attributes and
  Gatekeeper blocks the app even for the local user.
- **Toga + Briefcase on an older Python**: 3.9 / 3.10 hit edge cases
  with newer Toga versions. 3.11 / 3.12 are the tested range.
- **Concurrent AppImage builds**: Docker containerized — if a previous
  build left a dangling container, `docker rm` it or reboot Docker
  Desktop.
- **Port 5051 already in use**: pick another via the launcher UI or
  the Preferences page. The launcher persists the chosen port.

## License

MIT. See `LICENSE`.
