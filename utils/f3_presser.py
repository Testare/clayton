#!/usr/bin/env python
"""
f3_presser.py - A simple HTTP API that presses function keys (F1-F8) and the
space bar on Windows to remotely drive an emulator. Runs on port 62628.

Endpoints:
  GET/POST / or /press        - Sends F3 key press (back-compat), returns counter
  GET/POST /press/f<N>        - Sends F<N> key press (N in 1..8), returns counter
  GET      /ping              - Health check: {status: "ok"}
  GET      /status            - Returns current counter without pressing a key
  GET/POST /reset             - Resets counter to 0
  GET/POST /autospace/on      - Start auto-space mode (5s countdown, then repeats)
  GET/POST /autospace/off     - Stop auto-space mode
  GET      /autospace         - Report auto-space state

Auto-space mode repeatedly taps the space bar (the emulator's "A"/advance button)
so a battle plays out unattended. The repeat delay is asked for at startup
(default 1500 ms). Because Windows consoles don't reliably honor Ctrl+C, pressing
Enter (any terminal input) also cancels auto-space.
"""

import sys
import time
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# Configure logging to stdout
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

PORT = 62628
counter = 0
counter_lock = threading.Lock()

# --- Auto-space state -------------------------------------------------------
# Delay between space presses, in seconds (set at startup).
auto_space_delay = 1.5
COUNTDOWN_SECONDS = 5
_auto_space_thread = None
_auto_space_stop = threading.Event()
_auto_space_lock = threading.Lock()

# OS Detection
IS_WINDOWS = sys.platform.startswith('win')

if IS_WINDOWS:
    import ctypes
    # Virtual key codes: https://learn.microsoft.com/en-us/windows/win32/inputdev/virtual-key-codes
    VK_F1 = 0x70          # F1..F8 are contiguous: 0x70..0x77
    VK_SPACE = 0x20
    KEYEVENTF_KEYUP = 0x0002

    def _press_vk(vk):
        # Send key down event
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        # Small delay to simulate natural keypress duration
        time.sleep(0.05)
        # Send key up event
        ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

    def press_fkey(n):
        _press_vk(VK_F1 + (n - 1))

    def press_space():
        _press_vk(VK_SPACE)
else:
    def press_fkey(n):
        logging.info(f"[Mock] F{n} pressed (Running on non-Windows OS)")

    def press_space():
        logging.info("[Mock] Space pressed (Running on non-Windows OS)")


# --- Auto-space control -----------------------------------------------------
def _auto_space_loop():
    """Countdown, then tap space every auto_space_delay seconds until stopped."""
    for remaining in range(COUNTDOWN_SECONDS, 0, -1):
        if _auto_space_stop.is_set():
            logging.info("Auto-space cancelled during countdown.")
            return
        logging.info(f"Auto-space starting in {remaining}...")
        # Wait 1s but stay responsive to a stop request.
        if _auto_space_stop.wait(timeout=1.0):
            logging.info("Auto-space cancelled during countdown.")
            return

    logging.info(f"Auto-space active (every {auto_space_delay:.3f}s). "
                 "Press Enter in this terminal to stop.")
    while not _auto_space_stop.is_set():
        try:
            press_space()
        except Exception as e:
            logging.error(f"Error pressing space: {e}")
        # Sleep the configured delay, but wake immediately on stop.
        if _auto_space_stop.wait(timeout=auto_space_delay):
            break
    logging.info("Auto-space stopped.")


def start_auto_space():
    """Start auto-space mode if not already running. Returns True if started."""
    global _auto_space_thread
    with _auto_space_lock:
        if _auto_space_thread is not None and _auto_space_thread.is_alive():
            return False
        _auto_space_stop.clear()
        _auto_space_thread = threading.Thread(target=_auto_space_loop, daemon=True)
        _auto_space_thread.start()
        return True


def stop_auto_space():
    """Stop auto-space mode if running. Returns True if it was running."""
    global _auto_space_thread
    with _auto_space_lock:
        thread = _auto_space_thread
        if thread is None or not thread.is_alive():
            _auto_space_thread = None
            return False
        _auto_space_stop.set()
    thread.join(timeout=auto_space_delay + 1.0)
    with _auto_space_lock:
        _auto_space_thread = None
    return True


def auto_space_active():
    with _auto_space_lock:
        return _auto_space_thread is not None and _auto_space_thread.is_alive()


def _stdin_watcher():
    """Cancel auto-space on any terminal input (Enter-terminated line).

    Windows consoles don't reliably deliver Ctrl+C to a server loop, so a plain
    line of input is our reliable local stop signal.
    """
    for _ in sys.stdin:
        if auto_space_active():
            logging.info("Terminal input received - cancelling auto-space.")
            stop_auto_space()
        else:
            logging.info("Terminal input received (auto-space not running).")


class F3PressHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silence default log to keep console output clean
        pass

    def _send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_OPTIONS(self):
        # CORS preflight response
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        self._route_request()

    def do_POST(self):
        self._route_request()

    @staticmethod
    def _parse_fkey(token):
        """Parse 'f5'/'F5'/'5' -> 5, validating 1..8. Returns None if invalid."""
        token = token.lower()
        if token.startswith('f'):
            token = token[1:]
        if not token.isdigit():
            return None
        n = int(token)
        return n if 1 <= n <= 8 else None

    def _route_request(self):
        global counter

        path = self.path.split('?')[0].rstrip('/')  # Ignore query params/trailing slash
        parts = [p for p in path.split('/') if p]    # e.g. ['press', 'f5']

        # Health check
        if path == '/ping' or parts == ['ping']:
            self._send_json(200, {"status": "ok"})
            return

        # Auto-space controls
        if parts and parts[0] == 'autospace':
            action = parts[1] if len(parts) > 1 else 'status'
            if action == 'on':
                started = start_auto_space()
                self._send_json(200, {
                    "status": "success",
                    "autospace": "on",
                    "message": ("started" if started else "already running"),
                    "delay_ms": int(auto_space_delay * 1000),
                })
            elif action == 'off':
                stopped = stop_auto_space()
                self._send_json(200, {
                    "status": "success",
                    "autospace": "off",
                    "message": ("stopped" if stopped else "was not running"),
                })
            else:  # status
                self._send_json(200, {
                    "status": "success",
                    "autospace": "on" if auto_space_active() else "off",
                    "delay_ms": int(auto_space_delay * 1000),
                })
            return

        # Key press: '/', '/press' (default F3), or '/press/f<N>'
        fkey = None
        if not parts or parts == ['press']:
            fkey = 3  # back-compat default
        elif parts[0] == 'press' and len(parts) >= 2:
            fkey = self._parse_fkey(parts[1])
            if fkey is None:
                self._send_json(400, {
                    "status": "error",
                    "message": f"Invalid function key '{parts[1]}'. Use f1..f8."
                })
                return

        if fkey is not None:
            logging.info(f"HTTP Request received. Simulating F{fkey} key press...")
            try:
                press_fkey(fkey)
                success = True
                error_msg = None
            except Exception as e:
                logging.error(f"Error pressing F{fkey}: {e}")
                success = False
                error_msg = str(e)

            with counter_lock:
                if success:
                    counter += 1
                current_counter = counter

            logging.info(f"F{fkey} press complete. Counter value: {current_counter}")

            response = {
                "status": "success" if success else "error",
                "key": f"F{fkey}",
                "counter": current_counter,
            }
            if error_msg:
                response["error"] = error_msg
            self._send_json(200 if success else 500, response)
            return

        if path == '/status':
            with counter_lock:
                current_counter = counter
            self._send_json(200, {
                "status": "success",
                "counter": current_counter
            })
            return

        if path == '/reset':
            with counter_lock:
                counter = 0
                current_counter = counter
            logging.info("Counter reset to 0.")
            self._send_json(200, {
                "status": "success",
                "counter": current_counter,
                "message": "Counter reset successfully"
            })
            return

        self._send_json(404, {
            "status": "error",
            "message": ("Endpoint not found. Use '/press/f<N>' to press a key, "
                        "'/ping' for health, '/autospace/on|off' for auto-space, "
                        "'/status' for count, or '/reset' to reset.")
        })


def _prompt_auto_space_delay():
    """Ask for the auto-space repeat delay (ms). Falls back to default on EOF."""
    global auto_space_delay
    default_ms = 1500
    try:
        raw = input(f"Auto-space delay between space presses in ms [{default_ms}]: ").strip()
    except EOFError:
        raw = ""
    if raw:
        try:
            ms = int(raw)
            if ms <= 0:
                raise ValueError
            auto_space_delay = ms / 1000.0
        except ValueError:
            logging.warning(f"Invalid delay '{raw}', using default {default_ms} ms.")
            auto_space_delay = default_ms / 1000.0
    else:
        auto_space_delay = default_ms / 1000.0
    logging.info(f"Auto-space delay set to {int(auto_space_delay * 1000)} ms.")


def main():
    _prompt_auto_space_delay()

    # Watch stdin so Enter cancels auto-space (Ctrl+C is unreliable on Windows).
    threading.Thread(target=_stdin_watcher, daemon=True).start()

    server_address = ('', PORT)
    try:
        httpd = HTTPServer(server_address, F3PressHandler)
        logging.info(f"F3 Presser API Server started on port {PORT}")
        if not IS_WINDOWS:
            logging.warning("Not running on Windows! Key presses will be mocked.")
        logging.info("Press Ctrl+C to stop the server (Enter cancels auto-space).")
        httpd.serve_forever()
    except KeyboardInterrupt:
        logging.info("\nShutting down server...")
        stop_auto_space()
        httpd.server_close()
        logging.info("Server stopped.")
    except Exception as e:
        logging.error(f"Server error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
