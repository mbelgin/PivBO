"""Entry point for the packaged app.

Opens the PivBO control window (start/stop, port, open-in-browser).
Dev users still run `python pivbo_server.py` directly for a headless
Flask server; this module is what Briefcase installers launch.
"""

import os
import sys


def _bootstrap_sys_path():
    # os.path.realpath resolves symlinks so sys.path entries and later
    # __file__-based lookups always point at the REAL bundle dir, not a
    # symlink that launched us (winget portable installs create such a
    # symlink/alias; without realpath the bundled app_packages/ wouldn't
    # be found when invoked via the alias).
    here = os.path.dirname(os.path.realpath(__file__))
    parent = os.path.dirname(here)
    if parent not in sys.path:
        sys.path.insert(0, parent)


def _anchor_cwd_to_install():
    """Force CWD to the actual install directory (where PivBO.exe lives).

    When a user invokes the app via a winget-generated shell alias or
    symlink, their CWD is wherever they typed the command — NOT the
    install dir. Any code downstream that opens a relative file path
    (ours or a dependency's) would fail. Point CWD at the real install
    directory, discovered via realpath() to resolve any symlinks, so
    the behavior is identical to double-clicking PivBO.exe from File
    Explorer.
    """
    here = os.path.dirname(os.path.realpath(__file__))
    # __file__ is <install>/app/pivbo/__main__.py. Walk up two levels
    # to get the install root (where PivBO.exe lives alongside
    # python313.dll etc.).
    install_root = os.path.dirname(os.path.dirname(here))
    try:
        os.chdir(install_root)
    except OSError:
        pass


def main():
    _anchor_cwd_to_install()
    _bootstrap_sys_path()
    from pivbo.launcher import run
    run()


if __name__ == "__main__":
    main()
