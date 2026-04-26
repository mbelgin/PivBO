"""Desktop launcher window for PivBO.

A tiny Toga control panel (native WinForms on Windows, GTK on Linux,
Cocoa on macOS) that owns the Flask server lifecycle. Gives the user a
real window with a taskbar entry, a way to stop/start the server,
switch port when 5051 is busy, and reopen the browser tab without
hunting through the terminal.
"""

import os
import socket
import threading
import webbrowser

import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW
from waitress import create_server

LOOPBACK_HOST = "127.0.0.1"
LAN_HOST = "0.0.0.0"


def _detect_lan_ip():
    """Best-effort detection of the LAN IP this machine would advertise
    on its primary interface. The UDP socket trick lets the OS pick the
    interface that would route traffic to a non-local address, without
    actually sending anything. Falls back to loopback if offline.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        try:
            s.close()
        except Exception:
            pass


class _ServerThread(threading.Thread):
    """Run the Flask app via waitress in a background thread we can stop
    cleanly. Thread count is derived from the host's CPU count so the
    server scales from tiny laptops up to workstations without us
    picking a number that's wrong on both ends.
    """

    def __init__(self, flask_app, host, port):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        # Cap the pool at a modest number. A desktop app has exactly one
        # user; more than a handful of handler threads is memory for
        # nothing.
        thread_count = min(os.cpu_count() or 4, 8)
        self.server = create_server(
            flask_app,
            host=host,
            port=port,
            threads=thread_count,
            ident="pivbo",
        )

    def run(self):
        # Blocks until the listen socket is closed from shutdown().
        self.server.run()

    def shutdown(self):
        # close() stops accepting new connections; the run() loop exits
        # after in-flight requests finish (or are forcibly abandoned
        # when the daemon thread is GC'd on process exit).
        try:
            self.server.close()
        except Exception:
            pass


class PivBOLauncher(toga.App):
    def startup(self):
        # Bring Flask in only after sys.path has been bootstrapped in __main__.
        import pivbo_server
        self._flask_app = pivbo_server.app
        self._pivbo_server = pivbo_server
        self._server_thread = None
        self._auto_opened = False

        # Load persisted prefs so Port and Open-browser checkbox remember
        # the last choice across launches.
        try:
            self._prefs = pivbo_server._load_prefs()
        except Exception:
            self._prefs = {"port": pivbo_server.PORT, "autoOpenBrowser": True}

        title = toga.Label(
            "PivotBreakout",
            style=Pack(font_size=14, font_weight="bold", padding_bottom=2),
        )
        subtitle = toga.Label(
            "Open Source bar-by-bar trading simulator",
            style=Pack(font_size=9, color="#666", padding_bottom=12),
        )
        self._status = toga.Label(
            "starting...",
            style=Pack(padding_bottom=10, color="#333"),
        )

        self._port_input = toga.TextInput(
            value=str(self._prefs.get("port", pivbo_server.PORT)),
            style=Pack(width=70),
        )
        port_row = toga.Box(
            children=[
                toga.Label("Port:", style=Pack(padding_right=6)),
                self._port_input,
            ],
            style=Pack(direction=ROW, alignment="center", padding_bottom=8),
        )

        self._auto_open_switch = toga.Switch(
            "Open browser on start",
            value=bool(self._prefs.get("autoOpenBrowser", True)),
            on_change=self._on_auto_open_toggled,
            style=Pack(padding_bottom=4),
        )

        self._lan_switch = toga.Switch(
            "Listen on local network (other devices on your Wi-Fi can connect)",
            value=bool(self._prefs.get("listenOnLan", False)),
            on_change=self._on_lan_toggled,
            style=Pack(padding_bottom=2),
        )

        self._lan_caution = toga.Label(
            "Use only on networks you trust. Do not enable on public Wi-Fi.",
            style=Pack(font_size=9, color="#a04020", padding_bottom=10),
        )

        self._start_btn = toga.Button("Start", on_press=self._on_start, style=Pack(width=80, padding_right=6))
        self._stop_btn = toga.Button("Stop", on_press=self._on_stop, style=Pack(width=80, padding_right=6))
        self._open_btn = toga.Button("Open in Browser", on_press=self._on_open, style=Pack(width=160))
        self._stop_btn.enabled = False
        self._open_btn.enabled = False
        button_row = toga.Box(
            children=[self._start_btn, self._stop_btn, self._open_btn],
            style=Pack(direction=ROW, padding_bottom=12),
        )

        quit_btn = toga.Button("Quit", on_press=self._on_quit, style=Pack(width=100))

        main_box = toga.Box(
            children=[
                title,
                subtitle,
                self._status,
                port_row,
                self._auto_open_switch,
                self._lan_switch,
                self._lan_caution,
                button_row,
                quit_btn,
            ],
            style=Pack(direction=COLUMN, alignment="left", padding=18),
        )

        # Title bar reads "PivBO Launcher" so users have an unambiguous
        # name for this window when describing it (vs the browser-based
        # web UI). The OS taskbar tooltip / process name still uses the
        # bare formal_name from briefcase config.
        self.main_window = toga.MainWindow(title=self.formal_name + " Launcher", size=(520, 380))
        self.main_window.content = main_box
        self.main_window.show()

        # Auto-start once the window is on screen so a double-click just works.
        self.loop.call_later(0.25, self._auto_start)

    def _auto_start(self):
        if self._server_thread is None:
            self._start_server()

    def _set_running(self, running):
        self._start_btn.enabled = not running
        self._stop_btn.enabled = running
        self._open_btn.enabled = running
        self._port_input.enabled = not running
        # The bind host is fixed at server-creation time, so toggling the
        # switch while running would mislead. Disable until Stop+Start.
        self._lan_switch.enabled = not running

    def _start_server(self):
        if self._server_thread is not None:
            return
        try:
            port = int(self._port_input.value.strip())
        except ValueError:
            self._status.text = "invalid port"
            return

        try:
            self._pivbo_server._ensure_sim_dir()
            self._pivbo_server._ensure_templates_dir()
            self._pivbo_server._reap_stale_servers(port)
        except Exception:
            pass

        # Kick off the first-launch chart-data seeder. Idempotent — on
        # subsequent runs it's a near-instant no-op (just stat()s the
        # already-present .csv.gz files and returns). Runs in a daemon
        # thread so the Flask server starts immediately regardless.
        try:
            self._pivbo_server._seed_start_once()
        except Exception:
            pass

        listen_on_lan = bool(self._lan_switch.value)
        host = LAN_HOST if listen_on_lan else LOOPBACK_HOST

        try:
            self._server_thread = _ServerThread(self._flask_app, host, port)
            # Expose the thread on the Flask app so /api/server/stop can
            # reach into the launcher and shut down gracefully without
            # killing the whole process.
            self._flask_app._pivbo_server_thread = self._server_thread
            self._server_thread.start()
        except OSError:
            self._server_thread = None
            self._status.text = f"port {port} in use — try another"
            return
        except Exception as e:
            self._server_thread = None
            self._status.text = f"failed to start: {e}"
            return

        # Persist the port the user actually launched with, so next boot
        # defaults to the same choice.
        try:
            self._pivbo_server._save_prefs({"port": port})
            self._prefs["port"] = port
        except Exception:
            pass

        if listen_on_lan:
            lan_ip = _detect_lan_ip()
            self._status.text = (
                f"running on http://localhost:{port} "
                f"and http://{lan_ip}:{port} (LAN)"
            )
        else:
            self._status.text = f"running on http://localhost:{port}"
        self._set_running(True)

        if not self._auto_opened and self._prefs.get("autoOpenBrowser", True):
            self._auto_opened = True
            self.loop.call_later(0.4, self._open_browser)

    def _stop_server(self):
        t = self._server_thread
        if t is None:
            return
        self._status.text = "stopping..."
        try:
            t.shutdown()
        except Exception:
            pass
        try:
            t.join(timeout=3.0)
        except Exception:
            pass
        self._server_thread = None
        try:
            if hasattr(self._flask_app, "_pivbo_server_thread"):
                del self._flask_app._pivbo_server_thread
        except Exception:
            pass
        self._status.text = "stopped"
        self._set_running(False)

    def _open_browser(self):
        t = self._server_thread
        if t is None:
            return
        try:
            webbrowser.open(f"http://localhost:{t.port}/")
        except Exception:
            pass

    # --- button handlers ---

    def _on_start(self, widget):
        self._start_server()

    def _on_stop(self, widget):
        self._stop_server()

    def _on_open(self, widget):
        self._open_browser()

    def _on_quit(self, widget):
        # Run the visible Stop path first so Quit is an orderly handoff.
        self._stop_server()
        os._exit(0)

    def _on_auto_open_toggled(self, widget):
        val = bool(widget.value)
        self._prefs["autoOpenBrowser"] = val
        try:
            self._pivbo_server._save_prefs({"autoOpenBrowser": val})
        except Exception:
            pass

    def _on_lan_toggled(self, widget):
        val = bool(widget.value)
        self._prefs["listenOnLan"] = val
        try:
            self._pivbo_server._save_prefs({"listenOnLan": val})
        except Exception:
            pass


def run():
    # sys.path was set up in pivbo.__main__.main() before import.
    app = PivBOLauncher(formal_name="PivBO", app_id="com.pivbo.pivbo")
    app.main_loop()
