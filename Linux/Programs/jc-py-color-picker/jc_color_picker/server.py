"""Dependency-free HTTP server for the Joy-Con Color Picker.

Serves the static HTML/CSS/JS front-end and a small JSON API that the page uses
to load presets, persist them, and read/write colors on a connected controller.

Run with::

    python -m jc_color_picker            # auto-detects a controller, else mock
    python -m jc_color_picker --mock     # force the in-memory mock device
    python -m jc_color_picker --port 8753 --no-browser
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, joycon, presets

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


class AppState:
    """Shared, thread-safe application state (device handle + preset store)."""

    def __init__(self, prefer_mock: bool = False):
        self.prefer_mock = prefer_mock
        self.lock = threading.Lock()
        self.store = presets.PresetStore.load()
        self.device = joycon.open_device(prefer_mock=prefer_mock)

    def reconnect(self, prefer_mock: bool | None = None):
        if prefer_mock is None:
            prefer_mock = self.prefer_mock
        with self.lock:
            try:
                self.device.close()
            except Exception:
                pass
            self.device = joycon.open_device(prefer_mock=prefer_mock)
            return self.device.info()

    def device_info(self) -> dict:
        with self.lock:
            return self.device.info()

    def read_colors(self) -> dict:
        with self.lock:
            return self.device.read_colors()

    def write_colors(self, colors: dict) -> dict:
        with self.lock:
            self.device.write_colors(colors)
            return self.device.read_colors()

    def state(self) -> dict:
        with self.lock:
            info = self.device.info()
            try:
                colors = self.device.read_colors()
                error = None
            except joycon.JoyConError as exc:
                colors = None
                error = str(exc)
        return {
            "version": __version__,
            "device": info,
            "colors": colors,
            "device_error": error,
            "available": joycon.discover_devices(),
            "presets": presets.all_presets(self.store),
        }

    def save_presets(self, payload: dict) -> dict:
        with self.lock:
            self.store.update_from_payload(payload)
            self.store.save()
            return self.store.to_dict()


class Handler(BaseHTTPRequestHandler):
    server_version = f"jc-color-picker/{__version__}"
    app: AppState  # injected on the server instance

    # -- helpers -----------------------------------------------------------
    def _send_json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def log_message(self, fmt, *args):  # quieter logging
        if os.environ.get("JC_COLOR_PICKER_VERBOSE"):
            super().log_message(fmt, *args)

    # -- routing -----------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/state":
            return self._send_json(self.app.state())
        if path == "/api/device":
            info = self.app.device_info()
            try:
                info = {**info, "colors": self.app.read_colors()}
            except joycon.JoyConError as exc:
                info = {**info, "colors": None, "error": str(exc)}
            return self._send_json(info)
        return self._serve_static(path)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        payload = self._read_json()
        try:
            if path == "/api/device/connect":
                return self._send_json(self.app.reconnect(payload.get("mock")))
            if path == "/api/device/read":
                return self._send_json({"colors": self.app.read_colors()})
            if path == "/api/device/write":
                colors = payload.get("colors", payload)
                result = self.app.write_colors(colors)
                return self._send_json({"ok": True, "colors": result})
            if path == "/api/presets":
                return self._send_json({"ok": True, "presets": self.app.save_presets(payload)})
        except joycon.JoyConError as exc:
            return self._send_json({"ok": False, "error": str(exc)}, status=502)
        except Exception as exc:  # pragma: no cover - defensive
            return self._send_json({"ok": False, "error": repr(exc)}, status=500)
        return self._send_json({"error": "not found"}, status=404)

    # -- static files ------------------------------------------------------
    def _serve_static(self, path: str):
        if path == "/" or not path:
            path = "/index.html"
        rel = path.lstrip("/")
        full = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not full.startswith(WEB_DIR) or not os.path.isfile(full):
            return self._send_json({"error": "not found", "path": path}, status=404)
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_server(host: str, port: int, app: AppState) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"app": app})
    return ThreadingHTTPServer((host, port), handler)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="jc-color-picker",
        description="Joy-Con Color Picker — pure-Python Linux port (web UI).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8753, help="port (default: 8753)")
    parser.add_argument("--mock", action="store_true", help="force the in-memory mock device")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    args = parser.parse_args(argv)

    app = AppState(prefer_mock=args.mock)
    httpd = build_server(args.host, args.port, app)

    info = app.device_info()
    url = f"http://{args.host}:{args.port}/"
    print(f"Joy-Con Color Picker {__version__}")
    print(f"  device : {info['name']}" + ("  [mock]" if info["mock"] else f"  ({info['path']})"))
    print(f"  config : {app.store.path}")
    print(f"  serving: {url}")
    if info["mock"] and not args.mock:
        print("  note   : no accessible controller found — using mock. "
              "Connect one over Bluetooth and grant /dev/hidraw* access (see README).")

    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        httpd.server_close()
        try:
            app.device.close()
        except Exception:
            pass
    return 0
