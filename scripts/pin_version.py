"""Pin the package version in pyproject.toml and pivbo/__init__.py.

Usage:
    python scripts/pin_version.py v0.0.2         # CI form — leading 'v' is stripped
    python scripts/pin_version.py 0.0.2          # also fine
    python scripts/pin_version.py                # read current version, print both files

Runs in-place with surgical regex edits — no TOML parser dependency so
it works against bare Python in a Briefcase bundle with nothing else
installed. Stays inside the project root per project conventions.
"""
from __future__ import annotations
import os
import re
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPROJECT = os.path.join(ROOT, "pyproject.toml")
INIT_PY = os.path.join(ROOT, "pivbo", "__init__.py")

# Canonical version string grammar: N.N.N with optional pre-release
# suffix (e.g. "0.0.2-rc1"). Keep it simple — we don't need PEP 440
# strictness here.
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([.\-+][A-Za-z0-9.\-+]+)?$")


def strip_v(raw: str) -> str:
    return raw[1:] if raw.startswith(("v", "V")) else raw


def read_current() -> tuple[str, str]:
    """Return (pyproject_version, init_version)."""
    py = re.search(r'^version\s*=\s*"([^"]+)"', open(PYPROJECT, encoding="utf-8").read(), re.M)
    init = re.search(r'^__version__\s*=\s*"([^"]+)"', open(INIT_PY, encoding="utf-8").read(), re.M)
    return (py.group(1) if py else "?", init.group(1) if init else "?")


def write_version(new_version: str) -> None:
    if not VERSION_RE.match(new_version):
        raise SystemExit(f"Refusing to write invalid version {new_version!r}. Use N.N.N form.")

    # pyproject.toml: update the top-level `version = "..."` under [tool.briefcase]
    with open(PYPROJECT, encoding="utf-8") as f:
        py_src = f.read()
    py_new, py_n = re.subn(
        r'^(version\s*=\s*)"[^"]*"',
        f'\\1"{new_version}"',
        py_src,
        count=1,
        flags=re.M,
    )
    if py_n != 1:
        raise SystemExit("Could not find a `version = \"...\"` line in pyproject.toml")
    with open(PYPROJECT, "w", encoding="utf-8") as f:
        f.write(py_new)

    # pivbo/__init__.py: update `__version__ = "..."`
    with open(INIT_PY, encoding="utf-8") as f:
        init_src = f.read()
    init_new, init_n = re.subn(
        r'^(__version__\s*=\s*)"[^"]*"',
        f'\\1"{new_version}"',
        init_src,
        count=1,
        flags=re.M,
    )
    if init_n != 1:
        raise SystemExit("Could not find a `__version__ = \"...\"` line in pivbo/__init__.py")
    with open(INIT_PY, "w", encoding="utf-8") as f:
        f.write(init_new)


def main() -> int:
    if len(sys.argv) == 1:
        py_v, init_v = read_current()
        print(f"pyproject.toml  version     = {py_v}")
        print(f"pivbo/__init__ __version__ = {init_v}")
        if py_v != init_v:
            print("\nWARNING: the two files disagree. Run this script with a version"
                  " argument to pin them back in sync.")
            return 1
        return 0

    new = strip_v(sys.argv[1].strip())
    write_version(new)
    print(f"Pinned version to {new} in pyproject.toml and pivbo/__init__.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
