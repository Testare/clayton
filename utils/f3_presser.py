#!/usr/bin/env python
"""
f3_presser.py - A simple HTTP API that presses the F3 key on Windows.
Runs on port 62628.

Endpoints:
  GET/POST / or /press  - Sends F3 key press, increments counter, returns counter
  GET /status           - Returns current counter without pressing F3
  GET/POST /reset       - Resets counter to 0
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

# OS Detection
IS_WINDOWS = sys.platform.startswith('win')

if IS_WINDOWS:
    import ctypes
    # Virtual key code for F3: https://learn.microsoft.com/en-us/windows/win32/inputdev/virtual-key-codes
    VK_F3 = 0x72
    KEYEVENTF_KEYUP = 0x0002

    def press_f3():
        # Send key down event
        ctypes.windll.user32.keybd_event(VK_F3, 0, 0, 0)
        # Small delay to simulate natural keypress duration
        time.sleep(0.05)
        # Send key up event
        ctypes.windll.user32.keybd_event(VK_F3, 0, KEYEVENTF_KEYUP, 0)
else:
    def press_f3():
        logging.info("[Mock] F3 pressed (Running on non-Windows OS)")


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

    def _route_request(self):
        global counter
        
        path = self.path.split('?')[0]  # Ignore query parameters

        if path in ('/', '/press'):
            logging.info("HTTP Request received. Simulating F3 key press...")
            
            try:
                press_f3()
                success = True
                error_msg = None
            except Exception as e:
                logging.error(f"Error pressing F3: {e}")
                success = False
                error_msg = str(e)

            with counter_lock:
                if success:
                    counter += 1
                current_counter = counter

            logging.info(f"F3 press complete. Counter value: {current_counter}")
            
            response = {
                "status": "success" if success else "error",
                "counter": current_counter
            }
            if error_msg:
                response["error"] = error_msg
                
            self._send_json(200 if success else 500, response)

        elif path == '/status':
            with counter_lock:
                current_counter = counter
            self._send_json(200, {
                "status": "success",
                "counter": current_counter
            })

        elif path == '/reset':
            with counter_lock:
                counter = 0
                current_counter = counter
            logging.info("Counter reset to 0.")
            self._send_json(200, {
                "status": "success",
                "counter": current_counter,
                "message": "Counter reset successfully"
            })

        else:
            self._send_json(404, {
                "status": "error",
                "message": "Endpoint not found. Use '/' or '/press' to press F3, '/status' for count, or '/reset' to reset."
            })


def main():
    server_address = ('', PORT)
    try:
        httpd = HTTPServer(server_address, F3PressHandler)
        logging.info(f"F3 Presser API Server started on port {PORT}")
        if not IS_WINDOWS:
            logging.warning("Not running on Windows! F3 presses will be mocked.")
        logging.info("Press Ctrl+C to stop the server.")
        httpd.serve_forever()
    except KeyboardInterrupt:
        logging.info("\nShutting down server...")
        httpd.server_close()
        logging.info("Server stopped.")
    except Exception as e:
        logging.error(f"Server error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
