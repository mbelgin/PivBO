"""Entry point for the packaged app.

Opens the PivBO control window (start/stop, port, open-in-browser).
Dev users still run `python pivbo_server.py` directly for a headless
Flask server; this module is what Briefcase installers launch.
"""

import os
import sys


def _bootstrap_sys_path():
    here = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(here)
    if parent not in sys.path:
        sys.path.insert(0, parent)


def main():
    _bootstrap_sys_path()
    from pivbo.launcher import run
    run()


if __name__ == "__main__":
    main()
