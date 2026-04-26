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


def _unblock_motw_files():
    """Strip Zone.Identifier alternate data streams from bundled DLLs/PYDs.

    Windows attaches Mark-of-the-Web (MotW) to files that arrive via a
    browser, and sometimes via winget too. The .NET CLR refuses to load an
    Authenticode-unsigned assembly that carries MotW, which causes the
    pythonnet failure on first launch:

        RuntimeError: Failed to resolve Python.Runtime.Loader.Initialize
        from \\app_packages\\pythonnet\\runtime\\Python.Runtime.dll

    Stripping the Zone.Identifier ADS from every .dll/.pyd/.exe in the
    install tree upgrades them to "fully trusted," so the load attempt a
    few imports later succeeds. We do this BEFORE importing pivbo.launcher
    (which transitively imports toga -> toga_winforms -> clr -> pythonnet)
    so the cleanup is in place by the time .NET inspects the file.

    Idempotent and Windows-only. Cost is a directory walk plus a few
    thousand failing os.remove calls (most files don't have MotW), which
    runs in well under a second on cold disk and faster on warm. Safe
    in our threat model: the user has already chosen to run PivBO.exe,
    which is the trust boundary; stripping MotW from PivBO's own bundled
    DLLs is no different from a user clicking Unblock manually on the
    same files.

    Once Windows builds are code-signed (SignPath, see DISTRO_README
    TODO), this whole problem goes away and this function becomes a
    cheap no-op that we can leave in for safety.
    """
    if os.name != "nt":
        return
    here = os.path.dirname(os.path.realpath(__file__))
    install_root = os.path.dirname(os.path.dirname(here))
    targets = (".dll", ".pyd", ".exe")
    try:
        for dirpath, _dirnames, filenames in os.walk(install_root):
            for fname in filenames:
                if not fname.lower().endswith(targets):
                    continue
                # NTFS exposes alternate data streams via the `:streamname`
                # path suffix. Removing the Zone.Identifier stream is the
                # equivalent of PowerShell's Unblock-File on a single file.
                ads_path = os.path.join(dirpath, fname) + ":Zone.Identifier"
                try:
                    os.remove(ads_path)
                except OSError:
                    # ADS doesn't exist (most files), or we can't access it.
                    # Either way, move on without breaking startup.
                    pass
    except Exception:
        # Defensive: an unexpected walk error must NEVER prevent the app
        # from launching. The user's manual Unblock-File workaround
        # remains a fallback if this self-heal silently fails.
        pass


def main():
    _anchor_cwd_to_install()
    _bootstrap_sys_path()
    _unblock_motw_files()
    from pivbo.launcher import run
    run()


if __name__ == "__main__":
    main()
